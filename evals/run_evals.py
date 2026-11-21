#!/usr/bin/env python
"""Copilot evaluation harness.

Runs every case in evals/cases/*.jsonl through the real agent pipeline (guardrails, RAG, tools,
persistence) against an isolated SQLite database with mock market data, scores each case with
deterministic checks and writes a JSON report.

    uv run python evals/run_evals.py                        # offline rule-based model (CI)
    uv run python evals/run_evals.py --provider configured  # whatever LLM_* env configures (e.g. GPT-6 Luna)
    uv run python evals/run_evals.py --min-score 0.85 --category guardrails -v

Case format (one JSON object per line):
    {"id", "category", "prompt" | "turns": [...], "context"?: str, "expect": {check: value, ...}}
Checks: tools_any, tools_all, no_tools (["*"] = none), args, card_types, contains_any, not_contains, flags, blocked,
cites_title_any, no_citations, dsl_valid, dsl_kind, dsl_symbols, dsl_underlying, deployments_created,
grounded_quotes, grounded_chain, grounded_backtest, grounded_payoff.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _setup_env(provider: str) -> None:
    tmp = tempfile.mkdtemp(prefix="algo-evals-")
    os.environ.update({
        "ENVIRONMENT": "test", "DATABASE_URL": f"sqlite+aiosqlite:///{tmp}/evals.db", "REDIS_URL": "", "DATA_MODE": "mock",
        "EMBEDDED_WORKERS": "true", "LOG_JSON": "false", "LOG_LEVEL": "ERROR", "NSE_MCP_URL": "",
    })
    if provider == "offline":
        os.environ["LLM_PRIMARY_PROVIDER"] = "mock"
        os.environ["LLM_FALLBACKS"] = ""


def _fmt2(x: float) -> str:
    return f"{x:,.2f}"


class Checker:
    def __init__(self, turn: dict[str, Any], deployments: int, user_text: str) -> None:
        self.t = turn
        self.content = turn["content"] or ""
        self.low = self.content.lower()
        self.tools = [x["name"] for x in turn.get("tools", [])]
        self.cards = turn.get("cards", [])
        self.deployments = deployments
        self.user_text = user_text

    def _strategy_dsl(self) -> dict[str, Any] | None:
        for c in self.cards:
            if c.get("type") == "strategy" or (c.get("type") == "backtest" and c.get("dsl")):
                return c.get("dsl")
        return None

    def run(self, expect: dict[str, Any]) -> list[tuple[str, bool, str]]:
        out: list[tuple[str, bool, str]] = []
        for k, v in expect.items():
            ok, why = True, ""
            if k == "tools_any":
                ok = any(t in self.tools for t in v)
            elif k == "tools_all":
                ok = all(t in self.tools for t in v)
            elif k == "no_tools":
                ok = not self.tools if v == ["*"] else not any(t in self.tools for t in v)
            elif k == "args":
                ok = all(any(x["name"] == tool and all(x["args"].get(a) == b for a, b in exp.items()) for x in self.t["tools"])
                         for tool, exp in v.items())
            elif k == "card_types":
                ok = any(c.get("type") in v for c in self.cards)
            elif k == "contains_any":
                ok = any(s.lower() in self.low for s in v)
            elif k == "not_contains":
                hay = self.low + "\n" + self.user_text.lower()
                ok = not any(s.lower() in hay for s in v)
            elif k == "flags":
                ok = all(f in self.t.get("flags", []) for f in v)
            elif k == "blocked":
                ok = ("blocked" in self.t.get("flags", [])) == bool(v)
            elif k == "cites_title_any":
                ok = any(any(s.lower() in c["title"].lower() for s in v) for c in self.t.get("citations", []))
            elif k == "no_citations":
                ok = not self.t.get("citations")
            elif k.startswith("dsl_"):
                dsl = self._strategy_dsl()
                if dsl is None:
                    ok, why = False, "no strategy card"
                elif k == "dsl_valid":
                    card = next((c for c in self.cards if c.get("type") == "strategy"), {"valid": True})
                    ok = bool(card.get("valid")) == bool(v)
                elif k == "dsl_kind":
                    ok = dsl.get("kind") == v
                elif k == "dsl_symbols":
                    ok = set(v) <= set(dsl.get("universe", {}).get("symbols", []))
                elif k == "dsl_underlying":
                    ok = dsl.get("universe", {}).get("underlying") == v
            elif k == "deployments_created":
                ok = self.deployments == v
            elif k == "grounded_quotes":
                qs = [q for c in self.cards if c.get("type") == "quotes" for q in c.get("quotes", [])]
                ok = bool(qs) and all(_fmt2(q["ltp"]) in self.content for q in qs)
            elif k == "grounded_chain":
                c = next((c for c in self.cards if c.get("type") == "option_chain"), None)
                ok = c is not None and str(c["pcr"]) in self.content and str(int(c["max_pain"])) in self.content
            elif k == "grounded_backtest":
                c = next((c for c in self.cards if c.get("type") == "backtest"), None)
                ok = c is not None and c.get("metrics") is not None and f"{c['metrics']['trades']} trades" in self.content \
                    and str(c["metrics"]["sharpe"]) in self.content
            elif k == "grounded_payoff":
                c = next((c for c in self.cards if c.get("type") == "payoff"), None)
                ok = c is not None and all(f"{b:,.0f}" in self.content for b in c["breakevens"][:2])
            else:
                ok, why = False, f"unknown check {k}"
            if not ok and not why:
                why = f"expected {k}={v!r}"
            out.append((k, ok, why))
        return out


def _load_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    files = sorted(glob.glob(str(HERE / "cases" / "*.jsonl")))
    cases: list[dict[str, Any]] = []
    for f in files:
        for i, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                c = json.loads(line)
                c["_file"] = f"{Path(f).name}:{i}"
                cases.append(c)
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]

    return cases


async def _run(args: argparse.Namespace, cases: list[dict[str, Any]]) -> int:
    from sqlalchemy import func, select

    from ai_agent.agent import TurnInput, run_turn
    from ai_agent.rag import seed_corpus
    from algo_db import session as sess
    from algo_db.models import ChatMessage, Deployment, RiskLimit, User

    sess.configure_engine(os.environ["DATABASE_URL"])
    await sess.create_all()
    async with sess.session_scope() as db:
        try:
            from app.services.users import ensure_plans  # type: ignore[import-not-found]

            await ensure_plans(db)
        except ImportError:
            pass
        await seed_corpus(db)

    results = []
    started = time.perf_counter()
    for c in cases:
        async with sess.session_scope() as db:  # fresh user per case: isolated history, portfolio and quotas
            u = User(email=f"eval-{c['id']}@example.com", full_name="Eval", twofa=None)
            db.add(u)
            await db.flush()
            db.add(RiskLimit(user_id=u.id))
            uid = u.id
        turns = c.get("turns") or [c["prompt"]]
        sid = None
        last: dict[str, Any] = {}
        t0 = time.perf_counter()
        error = None
        try:
            for i, text in enumerate(turns):
                ctx = c.get("context") if i == len(turns) - 1 else None
                async for ev in run_turn(TurnInput(user_id=uid, text=text, session_id=sid, context=ctx)):
                    if ev["type"] == "done":
                        last = ev
                        sid = ev["session_id"]
        except Exception as exc:
            error = f"{exc.__class__.__name__}: {exc}"
        async with sess.session_scope() as db:
            deps = (await db.execute(select(func.count()).select_from(Deployment).where(Deployment.user_id == uid))).scalar_one()
            user_text = ""
            if sid:
                user_text = " ".join((await db.execute(select(ChatMessage.content).where(ChatMessage.session_id == sid,
                                                                                         ChatMessage.role == "user"))).scalars())
        if error or not last:
            checks = [("run", False, error or "no done event")]
        else:
            checks = Checker(last, int(deps), user_text).run(c["expect"])
        passed = sum(ok for _, ok, _ in checks)
        score = passed / len(checks) if checks else 0.0
        results.append({"id": c["id"], "category": c["category"], "score": round(score, 4), "passed": passed == len(checks),
                        "checks": [{"check": k, "ok": ok, "detail": why} for k, ok, why in checks],
                        "tools": [x["name"] for x in last.get("tools", [])], "flags": last.get("flags", []),
                        "provider": last.get("provider"), "latency_s": round(time.perf_counter() - t0, 2),
                        "answer": (last.get("content") or "")[:400], "file": c["_file"]})
        if args.verbose and passed != len(checks):
            print(f"✗ {c['id']} ({c['_file']}): {[w for _, ok, w in checks if not ok]} tools={results[-1]['tools']}")
            print(f"   prompt: {turns[-1][:120]}\n   answer: {(last.get('content') or '')[:200]!r}")

    by_cat: dict[str, list[float]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["score"])
    overall = sum(r["score"] for r in results) / len(results) if results else 0.0
    report = {
        "provider": args.provider, "cases": len(results), "overall_score": round(overall, 4),
        "pass_rate": round(sum(r["passed"] for r in results) / len(results), 4) if results else 0.0,
        "by_category": {k: {"cases": len(v), "score": round(sum(v) / len(v), 4)} for k, v in sorted(by_cat.items())},
        "runtime_s": round(time.perf_counter() - started, 1), "results": results,
    }
    await asyncio.to_thread(Path(args.report).write_text, json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nEvaluated {len(results)} cases with provider={args.provider} in {report['runtime_s']}s")
    for k, v in report["by_category"].items():
        print(f"  {k:<16} {v['cases']:>4} cases   score {v['score']:.3f}")
    print(f"  {'OVERALL':<16} {len(results):>4} cases   score {overall:.3f}   pass-rate {report['pass_rate']:.3f}")
    print(f"Report: {args.report}")
    await sess.dispose_engine()
    if overall < args.min_score:
        print(f"FAIL: overall score {overall:.3f} < --min-score {args.min_score}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["offline", "configured"], default="offline")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--report", default=str(HERE / "report.json"))
    ap.add_argument("--category", action="append")
    ap.add_argument("--case", action="append")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    _setup_env(args.provider)
    sys.path.insert(0, str(HERE.parent / "apps" / "api"))
    sys.exit(asyncio.run(_run(args, _load_cases(args))))


if __name__ == "__main__":
    main()

