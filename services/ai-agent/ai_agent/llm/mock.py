"""Offline rule-based "model".

Plans tool calls from the user's request with regex intents, chains multi-step plans
(e.g. generate_strategy -> run_backtest), then writes a grounded answer from the tool
results or from retrieved knowledge-base excerpts. It lets the whole agent pipeline
(tools, cards, citations, guardrails, persistence, evals) run without any API key.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from ai_agent import nlu
from ai_agent.guardrails import is_advice_request
from ai_agent.llm.base import (
    ChatMsg,
    Finish,
    LLMEvent,
    LLMProvider,
    TextDelta,
    Tier,
    ToolCall,
    ToolCallsEvent,
    ToolSpec,
    Usage,
    estimate_tokens,
)

Args = dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]
Step = tuple[str, Args]

def _sym_arg(text: str) -> dict[str, Any]:
    eqs = nlu.find_equities(text)
    return {"symbol": nlu.underlying_of(eqs[0])} if eqs else {}


_NSE_INTENTS: list[tuple[str, str, Callable[[str], dict[str, Any]]]] = [
    (r"\bfii|\bdii|\bfpi|institutional (flow|activity|investors)", "nse_get_fii_dii_activity", lambda t: {"days": 10}),
    (r"bulk deal|block deal", "nse_get_bulk_block_deals", lambda t: {"kind": "block" if "block" in t else "bulk"}),
    (r"results calendar|earnings calendar|upcoming results|board meeting", "nse_get_results_calendar", lambda t: {"days": 14}),
    (r"market breadth|advance[s]?[ -/]+decline|advancers", "nse_get_market_breadth", lambda t: {}),
    (r"shareholding|promoter holding|promoter stake|fii holding", "nse_get_shareholding_pattern",
     lambda t: {"symbol": nlu.underlying_of((nlu.find_equities(t) or ["NSE:RELIANCE"])[0])}),
    (r"corporate action|dividend|bonus issue|stock split|buyback|ex-date|record date", "nse_get_corporate_actions",
     lambda t: _sym_arg(t)),
    (r"announcement|filing|disclosure", "nse_get_corporate_announcements", lambda t: {**_sym_arg(t), "limit": 10}),
]

_STRUCTURES = [("iron condor", "iron_condor"), ("iron fly", "iron_fly"), ("iron butterfly", "iron_fly"),
               ("butterfly", "long_call_butterfly"), ("short straddle", "short_straddle"), ("long straddle", "long_straddle"),
               ("straddle", "short_straddle"), ("short strangle", "short_strangle"), ("long strangle", "long_strangle"),
               ("strangle", "short_strangle"), ("bull call", "bull_call_spread"), ("bear put", "bear_put_spread")]


def _structure(text: str) -> str | None:
    for k, v in _STRUCTURES:
        if k in text:
            return v
    return None


def _strategy_id(text: str) -> int | None:
    m = re.search(r"strategy\s*(?:#|id\s*|no\.?\s*)(\d+)", text)
    return int(m.group(1)) if m else None


_NEW_RULES = re.compile(r"\b(build|create|make|design|draft|write)\b|\bema\b|\bsma\b|\brsi\b|macd|supertrend|bollinger|breakout|"
                        r"straddle|strangle|condor|butterfly|\bpairs?\b|crossover|moving average")
_CONCEPTUAL = re.compile(r"\s*(what is|what's|whats|what are|what does|what do|explain|define|meaning of|how does|how do|how is|"
                         r"how are|why do|why does|why is|why are|difference between|when should|is it|can i|should i use)\b")
_LIVE_DATA = re.compile(r"\bmy\b|news|headline|today|right now|\bnow\b|current|latest|this week|flows? (are|is)? ?doing|"
                        r"\bfii|\bdii|breadth|results calendar|bulk|block deal|price of|trading at|\bltp\b|quote")
_REFERS_BACK = re.compile(r"\b(it|this|that|the above|same)\b")


def _period_days(t: str) -> int:
    m = re.search(r"(\d+)\s*(year|yr|y\b|month|mo\b|week|day)", t)
    if not m:
        return 365
    n, unit = int(m.group(1)), m.group(2)
    days = n * (365 if unit.startswith("y") else 30 if unit.startswith("mo") else 7 if unit.startswith("w") else 1)
    return max(30, min(days, 3650))


def plan_for(text: str, prior: dict[str, Any] | None = None) -> list[Step]:
    """Map a request to an ordered list of tool calls (later args may depend on earlier results)."""
    t = text.lower()
    prior = prior or {}
    prior_dsl = prior.get("strategy_dsl")
    reuse = bool(prior_dsl) and bool(_REFERS_BACK.search(t)) and not _NEW_RULES.search(t)
    syms = nlu.find_symbols(text)
    if _CONCEPTUAL.match(t) and not syms and not _LIVE_DATA.search(t):
        return []  # conceptual question: answer from the knowledge base
    eqs = nlu.find_equities(text)
    und = nlu.find_underlying(text)
    sid = _strategy_id(t)
    mode = "live" if re.search(r"\blive\b|real money", t) else "notify" if "notify" in t or "alert only" in t else "paper"

    if re.search(r"\bdeploy\b|go live|start (paper )?trading (it|this)|run it live|paper[- ]trade (it|this)", t):
        if sid:
            return [("deploy_strategy", {"strategy_id": sid, "mode": mode})]
        if not sid and (dep := prior.get("backtest", {}) or {}).get("strategy_id") and reuse:
            return [("deploy_strategy", {"strategy_id": dep["strategy_id"], "mode": mode})]
        if reuse:
            return [("deploy_strategy", {"dsl": prior_dsl, "mode": mode})]
        return [("generate_strategy", {"description": text}),
                ("deploy_strategy", lambda r: {"dsl": r.get("generate_strategy", {}).get("dsl"), "mode": mode})]
    if re.search(r"back-?test|how (would|did) .* (perform|do)|historical(ly)? perform|test (this|the|a|my) strategy", t):
        days = _period_days(t)
        if sid:
            return [("run_backtest", {"strategy_id": sid, "period_days": days})]
        if reuse:
            return [("run_backtest", {"dsl": prior_dsl, "period_days": days})]
        return [("generate_strategy", {"description": text}),
                ("run_backtest", lambda r: {"dsl": r.get("generate_strategy", {}).get("dsl"), "period_days": days})]
    if re.search(r"\b(build|create|generate|make|design|write|code|set ?up|draft)\b.{0,60}\b(strategy|algo|system|bot|straddle|strangle|"
                 r"condor|butterfly|iron fly|crossover|breakout|pair trade|spread)\b", t) \
            or re.search(r"\bstrategy (that|which|to|for|where|with)\b", t):
        return [("generate_strategy", {"description": text})]
    if re.search(r"option chain|\bpcr\b|put[- ]call ratio|max pain|open interest|\boi\b(?! ?(buildup)? ?scan)|oi buildup|implied vol", t):
        return [("get_option_chain", {"underlying": und})]
    if re.search(r"greeks|payoff|\bdelta\b|\btheta\b|\bvega\b", t) or (_structure(t) and not re.search(r"what is|explain|define", t)):
        return [("get_greeks", {"underlying": und, "structure": _structure(t) or "short_straddle"})]
    if re.search(r"arbitrage|cash[- ]?(and|&)[- ]?carry|calendar spread|ratio spread|pairs? (trade|trading|scan|candidates)|cointegrat", t):
        kind = ("pairs" if re.search(r"pair|cointegrat", t) else "ratio_spreads" if "ratio" in t else "arbitrage")
        return [("run_scanner", {"kind": kind, "underlying": und})]
    if re.search(r"\bscreen|screener|find (me )?(some )?stocks|stocks (with|that|where|having|trading)|list (of )?stocks|which stocks|shortlist", t):
        si = nlu.parse_screen(text)
        return [("run_screener", {"universe": si.universe, "conditions": si.conditions or [{"field": "rsi14", "op": "<", "value": 40}],
                                  "sort_by": si.sort_by, "descending": si.descending, "limit": 15})]
    for pat, tool, argf in _NSE_INTENTS:
        if re.search(pat, t):
            return [(tool, argf(text))]
    if re.search(r"\bnews\b|headline|what happened|why is .* (up|down|falling|rising|moving)|latest on", t):
        return [("get_news", {"symbol": eqs[0] if eqs else None, "limit": 8})]
    if re.search(r"portfolio|holdings|my positions|my p&l|my pnl|my trades", t):
        if re.search(r"analy|risk|concentrat|diversif|exposure|beta|review|health|overlap|allocation", t):
            return [("analyze_portfolio", {})]
        return [("get_portfolio", {})]
    if eqs and re.search(r"fundamental|valuation|\bp/?e\b|\broe\b|balance sheet|financials|revenue|profit|earnings|peers|overvalued|undervalued", t):
        return [("get_fundamentals", {"symbol": eqs[0]})]
    if syms and re.search(r"chart|candle|technical|trend|support|resistance|moving average|\brsi\b|macd|breakout|momentum", t):
        return [("get_candles", {"symbol": syms[0], "interval": nlu.find_interval(text)})]
    if syms and (re.search(r"price|quote|trading at|\bltp\b|how is|how's|doing|level|today|now|current", t) or len(t.split()) <= 4):
        return [("get_quote", {"symbols": syms[:6]})]
    if eqs and is_advice_request(text):
        return [("get_quote", {"symbols": eqs[:3]}), ("get_fundamentals", {"symbol": eqs[0]})]
    return []


# ---------------------------------------------------------------- answer composition


def _inr(v: Any, d: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    s = f"{abs(x):,.{d}f}"
    return ("-" if x < 0 else "") + "₹" + s


def _pct(v: Any, signed: bool = True) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{'+' if signed and x > 0 else ''}{x:.2f}%"


def _compose(name: str, d: dict[str, Any]) -> str:
    if d.get("error"):
        return f"I couldn't complete **{name}**: {d['error']}"
    if name == "get_quote":
        lines = []
        for q in d.get("quotes", []):
            sym = q["symbol"].split(":")[-1]
            rng = f" Day range {_inr(q.get('low'))}–{_inr(q.get('high'))}." if q.get("high") else ""
            lines.append(f"- **{sym}** {_inr(q.get('ltp'))} ({_pct(q.get('change_pct'))} today).{rng}")
        return "Here are the latest prices:\n\n" + "\n".join(lines) if lines else "No quotes were returned."
    if name == "get_candles":
        s = d.get("summary", {})
        lv = d.get("levels", [])
        sup = ", ".join(_inr(x["price"]) for x in lv if x.get("type") == "support")[:80] or "none nearby"
        res = ", ".join(_inr(x["price"]) for x in lv if x.get("type") == "resistance")[:80] or "none nearby"
        return (f"**{d.get('symbol', '').split(':')[-1]}** ({d.get('interval')}) looks **{s.get('trend', 'n/a')}** on my trend score "
                f"({s.get('score', '—')} on a −5…+5 scale): close {_inr(s.get('close'))}, EMA20 {_inr(s.get('ema20'))}, "
                f"EMA50 {_inr(s.get('ema50'))}, RSI {s.get('rsi', '—')}, ADX {s.get('adx', '—')}, Supertrend {s.get('supertrend', '—')}.\n\n"
                f"Support: {sup}. Resistance: {res}. "
                f"Recent patterns: {', '.join(p['pattern'].replace('_', ' ') for p in d.get('patterns', [])[-3:]) or 'none'}.")
    if name == "get_option_chain":
        a = d.get("analytics", {})
        pcr = d.get("pcr")
        tilt = "put writers dominate (often read as supportive)" if (pcr or 0) > 1.1 else \
            "call writers dominate (often read as capping upside)" if (pcr or 1) < 0.8 else "positioning is fairly balanced"
        rng = a.get("expected_range") or []
        return (f"**{d.get('underlying')}** option chain for {d.get('expiry')} — spot {_inr(d.get('spot'))}.\n\n"
                f"- PCR (OI) **{pcr}**: {tilt}.\n- Max pain **{d.get('max_pain')}**.\n"
                f"- ATM IV {a.get('atm_iv')}%, ATM straddle {_inr(a.get('atm_straddle'))} → implied ±1σ range "
                f"{_inr(rng[0], 0) if rng else '—'} – {_inr(rng[1], 0) if rng else '—'}.\n"
                f"- Highest call OI (resistance): {', '.join(str(int(x)) for x in a.get('resistance', [])) or '—'}; "
                f"highest put OI (support): {', '.join(str(int(x)) for x in a.get('support', [])) or '—'}.\n\n"
                "OI-based levels shift intraday; treat them as context, not signals.")
    if name == "get_greeks":
        g = d.get("greeks", {})
        mp, ml = d.get("max_profit"), d.get("max_loss")
        return (f"**{d.get('structure', '').replace('_', ' ').title()}** on {d.get('underlying')} ({d.get('expiry')}):\n\n"
                f"- Net premium {_inr(d.get('net_premium'), 0)} per set; max profit {'unlimited' if mp is None else _inr(mp, 0)}, "
                f"max loss {'unlimited' if ml is None else _inr(ml, 0)}.\n"
                f"- Breakevens {', '.join(_inr(b, 0) for b in d.get('breakevens', [])) or '—'}; probability of profit ≈ "
                f"{round((d.get('pop') or 0) * 100)}%.\n"
                f"- Greeks: Δ {g.get('delta')}, Γ {g.get('gamma')}, Θ {_inr(g.get('theta'), 0)}/day, vega {_inr(g.get('vega'), 0)} per vol point.")
    if name == "generate_strategy":
        dsl = d.get("dsl") or {}
        errs = d.get("errors") or []
        if errs:
            return "I drafted a strategy but it failed validation: " + "; ".join(e.get("msg", str(e)) for e in errs[:3])
        return (f"I drafted **{dsl.get('name')}** ({dsl.get('kind')}, {dsl.get('timeframe')} bars"
                f"{', ' + dsl.get('product', '') if dsl.get('product') else ''}). {d.get('explanation', '')}\n\n"
                "It is plain DSL JSON — open it in the Builder to tweak rules, then backtest before deploying.")
    if name == "run_backtest":
        m = d.get("metrics", {})
        warn = d.get("warnings") or []
        return (f"Backtest of **{d.get('name')}** ({d.get('period')}):\n\n"
                f"- Net P&L {_inr(m.get('net_pnl'), 0)} ({_pct(m.get('total_return_pct'))}); CAGR {_pct(m.get('cagr_pct'))}\n"
                f"- Sharpe {m.get('sharpe')}, max drawdown {_pct(m.get('max_drawdown_pct'), False)}, "
                f"{m.get('trades')} trades, win rate {_pct(m.get('win_rate_pct'), False)}, profit factor {m.get('profit_factor')}\n"
                f"- Charges {_inr(m.get('total_charges'), 0)} (STT, brokerage, exchange, GST, stamp duty)\n"
                + (f"\n⚠️ {' '.join(warn[:2])}\n" if warn else "")
                + "\nA single in-sample backtest can overfit — check walk-forward and Monte Carlo results in the Builder.")
    if name == "deploy_strategy":
        return (f"I've prepared a **{d.get('mode', 'paper')}** deployment of **{d.get('name')}**. Nothing has been started yet: "
                "review the parameters on the card and press **Confirm** to deploy"
                + (" (live trading needs your 2FA code)." if d.get("mode") == "live" else "."))
    if name == "run_screener":
        rows = d.get("rows", [])
        if not rows:
            return "No stocks matched those filters. Try loosening a threshold."
        names = ", ".join(r["symbol"].split(":")[-1] for r in rows[:8])
        conds = "; ".join(f"{c['field']} {c['op']} {c['value']}" for c in d.get("conditions", []))
        return f"**{d.get('matched')}** of {d.get('scanned')} stocks in {d.get('universe')} match ({conds}). Top results: {names}."
    if name == "run_scanner":
        kind = d.get("kind")
        rows = d.get("rows", [])
        if kind == "pairs":
            top = "; ".join(f"{r['a'].split(':')[-1]}/{r['b'].split(':')[-1]} (p={r['p_value']})" for r in rows[:5])
            return f"Most cointegrated pairs right now: {top}. Low p-values in-sample don't guarantee future mean reversion."
        if kind == "ratio_spreads":
            top = "; ".join(f"{r['type']} {int(r['buy_strike'])}/{r['ratio']}×{int(r['sell_strike'])} credit/lot {_inr(r['net_credit_per_lot'], 0)}"
                            for r in rows[:4])
            return f"Ratio-spread candidates: {top}. Remember these carry unlimited risk beyond the far breakeven."
        top = "; ".join(f"{r['symbol']} net {r['net_annualised_pct']}% p.a." for r in rows[:5])
        return f"Best cash-and-carry setups after ~{d.get('cost_bps')} bps costs: {top}."
    if name == "get_news":
        items = d.get("items", [])
        if not items:
            return "No recent news found."
        return "Latest headlines:\n\n" + "\n".join(f"- {i['title']} — *{i.get('source', '')}*, sentiment {i.get('sentiment', 'neutral')}"
                                                 for i in items[:6])
    if name == "get_fundamentals":
        r = d.get("ratios", {})
        return (f"**{d.get('name')}** ({d.get('sector')}): P/E {r.get('pe')}, P/B {r.get('pb')}, ROE {r.get('roe_pct')}%, "
                f"ROCE {r.get('roce_pct')}%, debt/equity {r.get('debt_to_equity')}, net margin {r.get('net_margin_pct')}%, "
                f"dividend yield {r.get('dividend_yield_pct')}%, 3-year revenue CAGR {r.get('revenue_growth_3y_pct')}%."
                + (" *(sample fundamentals — connect a data vendor for audited figures)*" if d.get("source") == "mock" else ""))
    if name == "get_portfolio":
        f = d.get("funds", {})
        pos = d.get("positions", [])
        return (f"Paper account: available {_inr(f.get('available'), 0)}, used margin {_inr(f.get('used_margin'), 0)}, "
                f"total {_inr(f.get('total'), 0)}. Open positions: {len([p for p in pos if p.get('quantity')])}; "
                f"day P&L {_inr(d.get('day_pnl'), 0)}.")
    if name == "analyze_portfolio":
        conc = d.get("concentration", {})
        return (f"Portfolio review: {d.get('positions')} positions, gross exposure {_inr(d.get('gross_exposure'), 0)}, "
                f"net {_inr(d.get('net_exposure'), 0)}. Largest position {conc.get('top_symbol') or '—'} at "
                f"{conc.get('top_weight_pct', 0)}% of gross; HHI {conc.get('hhi', 0)}. "
                + (" ".join(d.get("observations", [])) or ""))
    if name.startswith("nse_"):
        return _compose_nse(name, d)
    return f"Result from {name}: " + json.dumps(d, default=str)[:600]


def _compose_nse(name: str, d: dict[str, Any]) -> str:
    if name == "nse_get_fii_dii_activity":
        rows = d.get("rows") or d.get("data") or []
        if rows:
            last = rows[0]
            return (f"Institutional flows on {last.get('date')}: FII/FPI net {_inr(last.get('fii_net'), 0)} Cr, "
                    f"DII net {_inr(last.get('dii_net'), 0)} Cr. Over the last {len(rows)} sessions FIIs net "
                    f"{_inr(sum(r.get('fii_net', 0) for r in rows), 0)} Cr and DIIs {_inr(sum(r.get('dii_net', 0) for r in rows), 0)} Cr.")
    if name == "nse_get_market_breadth":
        return f"Market breadth: {d.get('advances')} advances, {d.get('declines')} declines, {d.get('unchanged')} unchanged."
    if name == "nse_get_shareholding_pattern":
        return (f"{d.get('symbol')} shareholding (as of {d.get('as_of')}): promoters {d.get('promoter')}%, FII {d.get('fii')}%, "
                f"DII {d.get('dii')}%, public {d.get('public')}%; {d.get('pledged_pct_of_promoter')}% of promoter shares pledged.")
    key = next((k for k, v in d.items() if isinstance(v, list)), None)
    items = d.get(key, []) if key else []
    if items:
        lines = []
        for it in items[:6]:
            lines.append("- " + ", ".join(f"{k}: {v}" for k, v in list(it.items())[:5]))
        return f"Here's the latest from NSE ({name.removeprefix('nse_get_').replace('_', ' ')}):\n\n" + "\n".join(lines)
    return json.dumps(d, default=str)[:600]


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'*\[-])")
_ABBR = re.compile(r"\b(i\.e|e\.g|vs|etc|Rs|approx|No)\.$", re.I)
_GENERIC = {"what", "the", "how", "does", "and", "for", "are", "why", "explain", "tell", "about", "with", "can", "you", "is", "on",
            "of", "in", "a", "an", "do", "i", "me", "my", "it", "this", "that", "work", "mean", "means", "define"}


def _sentences(text: str) -> list[str]:
    parts = _SENT.split(" ".join(text.split()))
    out: list[str] = []
    for p in parts:
        if out and _ABBR.search(out[-1]):
            out[-1] += " " + p
        else:
            out.append(p)
    return [p.strip() for p in out if p.strip()]


def _knowledge_answer(question: str, system: str) -> str | None:
    """Extractive answer from the <knowledge> excerpts in the system prompt, with [n] citations.

    Sentences are scored by IDF-weighted overlap with the question; a chunk's section heading counts as context for its
    sentences (definitions rarely repeat the term being defined)."""
    blocks = re.findall(r"\[(\d+)\] ([^\n]*)\n(.*?)(?=\n\[\d+\] |\n</knowledge>)", system, flags=re.S)
    if not blocks:
        return None
    from ai_agent.rag.text import tokenize

    terms = set(tokenize(question)) - set(tokenize(" ".join(_GENERIC)))
    if not terms:
        return None
    sents: list[tuple[int, int, str, set[str], set[str]]] = []  # (block n, position, text, tokens, heading tokens)
    tables: list[tuple[int, str]] = []
    for n, label, body in blocks:
        heading = label.split(" — ")[-1].split(" › ")[-1] if " — " in label else ""
        htoks = set(tokenize(heading))
        prose, table = [], []
        for line in body.split("\n"):
            (table if line.strip().startswith("|") else prose).append(line)
        for i, sent in enumerate(_sentences(" ".join(prose))):
            if len(sent) >= 25:
                sents.append((int(n), i, sent, set(tokenize(sent)), htoks))
        if len(table) > 2:
            hit = [r for r in table[2:] if terms & set(tokenize(r))]
            if hit:
                tables.append((int(n), "\n".join([table[0], table[1], *hit[:6]])))
    if not sents and not tables:
        return None
    import math

    df = {t: sum(1 for x in sents if t in x[3] or t in x[4]) for t in terms}
    idf = {t: math.log(1 + len(sents) / (1 + df[t])) for t in terms}
    q_mass = sum(idf[t] for t in terms if df[t]) or 1.0

    def score(x: tuple[int, int, str, set[str], set[str]]) -> float:
        n, i, sent, toks, htoks = x
        own = sum(idf[t] for t in terms if t in toks)
        ctx = sum(idf[t] for t in terms if t in htoks and t not in toks) * (0.9 if i < 2 else 0.5)
        lead = set(tokenize(" ".join(sent.split()[:7])))  # definitions lead with the term ("**Max pain.** The strike…")
        definitional = 0.35 * sum(idf[t] for t in terms if t in lead) / q_mass
        if i == 0 and terms <= (htoks | toks):  # opening sentence of the section about this very term
            definitional += 0.35
        m = re.match(r"\*\*([^*]{2,60})\.\*\*", sent)  # glossary entry: "**Term.** definition"
        if m and terms & set(tokenize(m.group(1))):
            definitional += 0.4
        if sent.startswith("- "):
            definitional -= 0.1
        return (own + ctx) / q_mass + definitional + (0.15 if i < 2 else 0) - (n - 1) * 0.12

    ranked = sorted(sents, key=score, reverse=True)
    chosen: list[tuple[int, int, str, set[str], set[str]]] = []
    if ranked and score(ranked[0]) >= 0.55:
        top = ranked[0]
        # lead paragraph: the best sentence and the two that follow it in the same excerpt
        chosen = [x for x in sorted((x for x in sents if x[0] == top[0]), key=lambda x: x[1]) if top[1] <= x[1] < top[1] + 3]
        other = next((x for x in ranked if x[0] != top[0] and score(x) >= 0.8), None)
        if other is not None:
            chosen.append(other)
    if not chosen and not tables:
        return None
    out = " ".join(f"{x[2]} [{x[0]}]" for x in chosen)
    if tables:
        n, tbl = tables[0]
        out = (out + "\n\n" if out else "") + tbl + f"\n\n_Source: [{n}]_"
    return out


HELP = ("I can help with Indian markets research and algo trading: live **quotes** and **charts**, **option chains** (PCR, max pain, OI), "
        "**payoffs and Greeks** for structures like iron condors, **screeners** and **scanners** (arbitrage, pairs, ratio spreads), "
        "**NSE data** (FII/DII flows, corporate actions, results calendar), **fundamentals**, **news**, your **paper portfolio**, and I can "
        "**draft strategies as DSL JSON, backtest them** and prepare deployments for your confirmation. What would you like to look at?")


class MockProvider(LLMProvider):
    name = "mock"

    def model_for(self, tier: Tier) -> str:
        return "algodesk-offline-1"

    async def stream(
        self, messages: list[ChatMsg], tools: list[ToolSpec], *, model: str, max_tokens: int = 1500, temperature: float = 0.2
    ) -> AsyncIterator[LLMEvent]:
        available = {t.name for t in tools}
        system = "\n".join(m.content for m in messages if m.role == "system")
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        question = messages[last_user].content if last_user >= 0 else ""
        # strip any dashboard context the agent appended to the user turn
        question = question.split("\n\n<dashboard_context>")[0]
        tail = messages[last_user + 1:]
        prior: dict[str, Any] = {}
        for m in messages[:last_user]:
            if m.role == "assistant" and "<prior_tool_results>" in m.content:
                try:
                    prior.update(json.loads(m.content.split("<prior_tool_results>", 1)[1].split("</prior_tool_results>")[0]))
                except (json.JSONDecodeError, IndexError):
                    pass
        results: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for m in tail:
            if m.role == "tool" and m.name:
                try:
                    results[m.name] = json.loads(m.content)
                except json.JSONDecodeError:
                    results[m.name] = {"error": "unparseable tool output"}
                order.append(m.name)
        tokens_in = sum(estimate_tokens(m.content) for m in messages)

        if available:
            plan = [s for s in plan_for(question, prior) if s[0] in available]
            pending = [s for s in plan if s[0] not in results]
            # stop chaining when a prerequisite failed
            if pending and not any(r.get("error") for r in results.values()):
                name, args = pending[0]
                resolved = args(results) if callable(args) else args
                yield ToolCallsEvent([ToolCall(id=f"call_{name}_{len(order)}", name=name, arguments=resolved)])
                yield Finish(Usage(tokens_in, 20), model, self.name, "tool_calls")
                return

        if order:
            body = "\n\n".join(_compose(n, results[n]) for n in dict.fromkeys(order))
        else:
            body = _knowledge_answer(question, system) or HELP
        if is_advice_request(question) and "ADVICE_ENABLED=false" in system:
            body = ("I can't tell you whether to buy or sell — that would be personalised investment advice, which requires SEBI "
                    "registration. Here is the objective data so you can decide for yourself:\n\n" + body)
        out = 0
        for chunk in re.findall(r"\S+\s*", body):
            out += 1
            yield TextDelta(chunk)
            if out % 8 == 0:
                await asyncio.sleep(0)
        yield Finish(Usage(tokens_in, estimate_tokens(body)), model, self.name, "stop")
