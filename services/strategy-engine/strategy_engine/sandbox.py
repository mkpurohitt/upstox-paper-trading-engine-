"""Sandbox for user-supplied Python (advanced mode).

Two entry points:
* `run_custom_indicator(code, df, params)` - ``def compute(df, params)`` returning
  a Series/array aligned to ``df``.
* `compile_strategy_code(code)` - runs code-mode builder scripts that produce a
  Strategy DSL document (the DSL is then validated like any other).

Defence in depth:
1. **Static AST allow-list**: no imports, no dunder/private attribute access,
   no exec/eval/open/getattr..., no I/O-capable numpy/pandas attributes, no
   classes/globals/async/yield.
2. **Separate process** started with ``python -I -B`` (isolated mode), an empty
   environment, a throw-away working directory, and only a minimal builtins
   table inside the exec namespace.
3. **Resource limits** (``setrlimit``): CPU seconds, address space, zero file
   writes, few file descriptors; plus a wall-clock timeout.

In production run workers under a seccomp/AppArmor profile without network
access (see ARCHITECTURE.md) for kernel-level isolation.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np
import pandas as pd

MAX_CODE_CHARS = 20_000
CPU_SECONDS = 8
WALL_SECONDS = 15
MEMORY_BYTES = 2 * 1024**3

_ALLOWED_NODES = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.AugAssign, ast.AnnAssign,
    ast.Expr, ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass, ast.BinOp, ast.UnaryOp, ast.BoolOp,
    ast.Compare, ast.Call, ast.Name, ast.Load, ast.Store, ast.Del, ast.Delete, ast.Constant, ast.Attribute,
    ast.Subscript, ast.Slice, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp,
    ast.GeneratorExp, ast.comprehension, ast.IfExp, ast.Lambda, ast.keyword, ast.Starred, ast.JoinedStr,
    ast.FormattedValue, ast.Raise, ast.Assert,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)
_FORBIDDEN_NAMES = {
    "exec", "eval", "compile", "open", "__import__", "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "input", "breakpoint", "help", "exit", "quit", "memoryview", "type", "object", "super", "classmethod",
    "staticmethod", "property", "dir", "id", "hash", "__builtins__", "__loader__", "__spec__", "importlib", "os",
    "sys", "subprocess", "socket", "builtins", "pickle", "marshal", "ctypes", "shutil", "pathlib", "io",
}
_FORBIDDEN_ATTRS = {
    "load", "loads", "save", "savez", "savez_compressed", "fromfile", "tofile", "memmap", "loadtxt", "savetxt",
    "genfromtxt", "fromregex", "ctypeslib", "lib", "f2py", "testing", "distutils", "DataSource", "os", "sys",
    "read_csv", "read_json", "read_pickle", "read_parquet", "read_excel", "read_html", "read_sql", "read_sql_query",
    "read_hdf", "read_feather", "read_orc", "read_xml", "read_clipboard", "read_table", "read_fwf", "read_sas",
    "read_spss", "read_stata", "to_csv", "to_pickle", "to_parquet", "to_excel", "to_json", "to_sql", "to_hdf",
    "to_feather", "to_orc", "to_xml", "to_clipboard", "to_stata", "to_html", "to_latex", "to_markdown",
    "eval", "query", "pipe", "apply_along_axis", "frompyfunc", "vectorize", "set_printoptions", "show_config",
    "f_globals", "f_locals", "gi_frame", "cr_frame", "tb_frame", "func_globals",
}


class SandboxError(Exception):
    pass


def validate_code(code: str) -> ast.Module:
    if len(code) > MAX_CODE_CHARS:
        raise SandboxError(f"code too long (max {MAX_CODE_CHARS} chars)")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxError(f"syntax error on line {exc.lineno}: {exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise SandboxError(f"'{type(node).__name__}' is not allowed (line {getattr(node, 'lineno', '?')})")
        if isinstance(node, ast.Name) and (node.id in _FORBIDDEN_NAMES or node.id.startswith("__")):
            raise SandboxError(f"name '{node.id}' is not allowed (line {node.lineno})")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _FORBIDDEN_ATTRS):
            raise SandboxError(f"attribute '.{node.attr}' is not allowed (line {node.lineno})")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            raise SandboxError(f"string constants containing '__' are not allowed (line {node.lineno})")
    return tree


_RUNNER = r'''
import json, math, sys
cpu, mem = int(sys.argv[1]), int(sys.argv[2])
try:
    import resource  # POSIX only; on Windows the parent's wall-clock timeout is the limit
except ImportError:
    resource = None
if resource is not None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except (ValueError, OSError):
        pass
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    del resource
payload = json.loads(sys.stdin.read())
import numpy as np, pandas as pd
SAFE = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k) for k in (
    "abs", "min", "max", "sum", "len", "range", "enumerate", "zip", "round", "float", "int", "bool", "str",
    "list", "dict", "tuple", "set", "sorted", "reversed", "any", "all", "map", "filter", "isinstance", "pow",
    "divmod", "ValueError", "TypeError", "ZeroDivisionError", "Exception", "print", "frozenset", "slice", "None",
    "True", "False") if (k in __builtins__ if isinstance(__builtins__, dict) else hasattr(__builtins__, k))}

def emit(obj):
    sys.stdout.write("\n__SANDBOX__" + json.dumps(obj))
    sys.stdout.flush()

PRICE = {"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4"}

class Cond:
    def __init__(self, d): self.d = d
    def __and__(self, o): return Cond({"kind": "all", "conditions": [self.d, _c(o)]})
    def __or__(self, o): return Cond({"kind": "any", "conditions": [self.d, _c(o)]})

def _c(x):
    if isinstance(x, Cond): return x.d
    if isinstance(x, dict): return x
    raise ValueError("expected a condition")

class Ind:
    def __init__(self, ref, offset=0): self.ref, self.offset = ref, offset
    def __getitem__(self, out): return Ind(self.ref + "." + out, self.offset)
    def prev(self, n=1): return Ind(self.ref, self.offset + n)
    def op(self): return {"type": "indicator", "ref": self.ref, "offset": self.offset}
    def __gt__(self, o): return Cond(_cmp(self, ">", o))
    def __lt__(self, o): return Cond(_cmp(self, "<", o))
    def __ge__(self, o): return Cond(_cmp(self, ">=", o))
    def __le__(self, o): return Cond(_cmp(self, "<=", o))

class Price(Ind):
    def __init__(self, field="close", offset=0): self.field, self.offset = field, offset
    def prev(self, n=1): return Price(self.field, self.offset + n)
    def op(self): return {"type": "price", "field": self.field, "offset": self.offset}

def _o(x):
    if isinstance(x, Ind): return x.op()
    if isinstance(x, str) and x in PRICE: return {"type": "price", "field": x}
    if isinstance(x, (int, float)): return {"type": "const", "value": float(x)}
    raise ValueError("operand must be an indicator, price field or number")

def _cmp(a, op, b): return {"kind": "compare", "left": _o(a), "op": op, "right": _o(b)}
def crosses_above(a, b): return Cond(_cmp(a, "crosses_above", b))
def crosses_below(a, b): return Cond(_cmp(a, "crosses_below", b))
def gt(a, b): return Cond(_cmp(a, ">", b))
def lt(a, b): return Cond(_cmp(a, "<", b))
def ge(a, b): return Cond(_cmp(a, ">=", b))
def le(a, b): return Cond(_cmp(a, "<=", b))
def price(field="close", offset=0): return Price(field, offset)
def time_between(after=None, before=None): return Cond({"kind": "time", "after": after, "before": before})
def on_days(*days): return Cond({"kind": "day_of_week", "days": [d.upper()[:3] for d in days]})
def pattern(name, lookback=20): return Cond({"kind": "pattern", "name": name, "lookback": lookback})
def all_of(*cs): return Cond({"kind": "all", "conditions": [_c(c) for c in cs]})
def any_of(*cs): return Cond({"kind": "any", "conditions": [_c(c) for c in cs]})

def _grp(c):
    d = _c(c)
    return d if d.get("kind") in ("all", "any") else {"kind": "all", "conditions": [d]}

class Strategy:
    def __init__(self):
        self.name, self.description = "Code strategy", ""
        self._d = {"dsl_version": "1.0", "kind": "equity", "universe": {"symbols": []}, "timeframe": "15m",
                   "product": "MIS", "indicators": [], "entry": {}, "exit": {}, "legs": [], "options_exit": {}}
    def kind(self, k): self._d["kind"] = k
    def universe(self, symbols=None, underlying=None):
        if symbols: self._d["universe"]["symbols"] = list(symbols)
        if underlying: self._d["universe"]["underlying"] = underlying
    def timeframe(self, tf): self._d["timeframe"] = tf
    def product(self, p): self._d["product"] = p
    def indicator(self, id, kind, source="close", **params):
        self._d["indicators"].append({"id": id, "kind": kind.upper(), "params": params, "source": source})
        return Ind(id)
    def custom_indicator(self, id, code, **params):
        self._d["indicators"].append({"id": id, "kind": "CUSTOM", "params": params, "code": code})
        return Ind(id)
    def entry_long(self, c): self._d["entry"]["long"] = _grp(c)
    def entry_short(self, c): self._d["entry"]["short"] = _grp(c)
    def exit_long(self, c): self._d["exit"]["long"] = _grp(c)
    def exit_short(self, c): self._d["exit"]["short"] = _grp(c)
    def _stop(self, percent=None, points=None, atr=None, atr_period=14):
        if percent is not None: return {"type": "percent", "value": percent}
        if points is not None: return {"type": "points", "value": points}
        if atr is not None: return {"type": "atr", "value": atr, "atr_period": atr_period}
        raise ValueError("give percent=, points= or atr=")
    def stop_loss(self, **kw): self._d["exit"]["stop_loss"] = self._stop(**kw)
    def target(self, **kw): self._d["exit"]["target"] = self._stop(**kw)
    def trailing(self, percent=None, points=None, activate_after=0.0):
        self._d["exit"]["trailing_sl"] = {"type": "percent" if percent is not None else "points",
                                          "value": percent if percent is not None else points, "activate_after": activate_after}
    def max_holding(self, bars): self._d["exit"]["max_holding_bars"] = bars
    def sizing(self, mode="capital_pct", value=10): self._d["sizing"] = {"mode": mode, "value": value}
    def schedule(self, **kw): self._d["schedule"] = kw
    def reentry(self, enabled=True, max_per_day=1, cooldown_bars=0):
        self._d["reentry"] = {"enabled": enabled, "max_per_day": max_per_day, "cooldown_bars": cooldown_bars}
    def risk(self, **kw): self._d["risk"] = kw
    def leg(self, action, option_type, offset=0, delta=None, premium=None, expiry="current", lots=1,
            stop_loss_pct=None, target_pct=None, id=None):
        mode = "DELTA" if delta is not None else ("PREMIUM" if premium is not None else "ATM_OFFSET")
        strike = {"mode": mode, "offset": offset}
        if delta is not None: strike["delta"] = delta
        if premium is not None: strike["premium"] = premium
        self._d["legs"].append({"id": id or "leg%d" % (len(self._d["legs"]) + 1), "action": action.upper(),
                                "option_type": option_type.upper(), "strike": strike, "expiry": expiry, "lots": lots,
                                "stop_loss_pct": stop_loss_pct, "target_pct": target_pct})
    def options_exit(self, **kw): self._d["options_exit"].update(kw)
    def pair(self, leg_a, leg_b, **kw): self._d["pair"] = {"leg_a": leg_a, "leg_b": leg_b, **kw}
    def tags(self, *t): self._d["tags"] = list(t)
    def to_dsl(self):
        d = dict(self._d)
        d["name"], d["description"] = self.name, self.description
        return d

try:
    code = payload["code"]
    if payload["mode"] == "indicator":
        df = pd.DataFrame(payload["data"])
        df.index = pd.to_datetime(payload["index"], utc=True)
        g = {"__builtins__": SAFE, "np": np, "pd": pd, "math": math}
        exec(compile(code, "<user>", "exec"), g)
        if "compute" not in g:
            raise ValueError("define compute(df, params)")
        out = g["compute"](df, dict(payload["params"]))
        arr = np.asarray(out, dtype=float).reshape(-1)
        if len(arr) != len(df):
            raise ValueError("compute() must return one value per bar (got %d, expected %d)" % (len(arr), len(df)))
        emit({"ok": True, "values": [None if not math.isfinite(v) else float(v) for v in arr]})
    else:
        strategy = Strategy()
        g = {"__builtins__": SAFE, "np": np, "math": math, "strategy": strategy, "crosses_above": crosses_above,
             "crosses_below": crosses_below, "gt": gt, "lt": lt, "ge": ge, "le": le, "price": price,
             "time_between": time_between, "on_days": on_days, "pattern": pattern, "all_of": all_of, "any_of": any_of}
        exec(compile(code, "<user>", "exec"), g)
        emit({"ok": True, "dsl": strategy.to_dsl()})
except Exception as exc:
    emit({"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:500]})
'''


def _run(payload: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="algo-sbx-") as tmp:
        env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "1",
               "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "HOME": tmp}
        # allow the interpreter to find numpy/pandas from the current environment
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p and "site-packages" in p)
        if os.name == "nt":
            # Windows: the interpreter needs SYSTEMROOT (crypto/random init) and PATH to load numpy's DLLs.
            env.update({k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "PATH") if k in os.environ})
            env["USERPROFILE"] = tmp
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-B", "-c", _RUNNER, str(CPU_SECONDS), str(MEMORY_BYTES)],
                input=json.dumps(payload), capture_output=True, text=True, timeout=WALL_SECONDS, cwd=tmp, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(f"execution exceeded {WALL_SECONDS}s") from exc
    marker = proc.stdout.rfind("\n__SANDBOX__")
    if marker < 0:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
        if proc.returncode and proc.returncode < 0:
            raise SandboxError(f"terminated by resource limit (signal {-proc.returncode})")
        raise SandboxError(f"sandbox failed: {err[0][:300]}")
    out = json.loads(proc.stdout[marker + len("\n__SANDBOX__"):])
    if not out.get("ok"):
        raise SandboxError(out.get("error", "unknown error"))
    out["stdout"] = proc.stdout[:marker][-2000:]
    return out


def run_custom_indicator(code: str, df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    validate_code(code)
    payload = {
        "mode": "indicator", "code": code, "params": params,
        "data": {c: df[c].astype(float).tolist() for c in ("open", "high", "low", "close", "volume") if c in df},
        "index": [ts.isoformat() for ts in df.index],
    }
    out = _run(payload)
    return pd.Series([np.nan if v is None else v for v in out["values"]], index=df.index, dtype=float)


def compile_strategy_code(code: str) -> tuple[dict[str, Any], str]:
    """Run a code-mode builder script; returns (dsl_dict, captured_stdout)."""
    validate_code(code)
    out = _run({"mode": "strategy", "code": code})
    return out["dsl"], out.get("stdout", "")


CODE_TEMPLATE = '''# Code mode: build a strategy with the AlgoDesk Python builder.
# Runs in a sandbox (no imports, no I/O). The result compiles to the same DSL as
# the form and visual builders. Available: strategy, crosses_above/below, gt/lt/ge/le,
# price(), time_between(), on_days(), pattern(), all_of(), any_of(), np, math.

strategy.name = "EMA 9/21 crossover with RSI filter"
strategy.universe(["NSE:RELIANCE", "NSE:INFY"])
strategy.timeframe("15m")
strategy.product("MIS")

fast = strategy.indicator("ema_fast", "EMA", period=9)
slow = strategy.indicator("ema_slow", "EMA", period=21)
rsi = strategy.indicator("rsi", "RSI", period=14)

# Custom indicator, executed in the sandbox at backtest/run time
mom = strategy.custom_indicator("mom", """
def compute(df, params):
    return df["close"].pct_change(int(params["n"])) * 100
""", n=10)

strategy.entry_long(crosses_above(fast, slow) & (rsi < 70) & (mom > 0))
strategy.exit_long(crosses_below(fast, slow))
strategy.stop_loss(percent=1.0)
strategy.target(percent=2.0)
strategy.trailing(percent=0.8, activate_after=0.5)
strategy.sizing("capital_pct", 20)
strategy.schedule(entry_after="09:30", entry_before="14:45", square_off="15:15")
strategy.risk(max_loss_per_day=10000, max_trades_per_day=6)
'''
