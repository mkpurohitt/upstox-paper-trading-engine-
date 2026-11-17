"""Portfolio analytics shared by the Portfolio page and the copilot's analyze_portfolio tool."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from market_data.symbols import parse, underlying_spot_symbol
from market_data.universe import BY_SYMBOL


def _underlying_asset(symbol: str):  # type: ignore[no-untyped-def]
    a = BY_SYMBOL.get(symbol)
    if a is not None:
        return a
    try:
        p = parse(symbol)
    except (ValueError, KeyError):
        return None
    return BY_SYMBOL.get(underlying_spot_symbol(p.underlying)) if p.underlying else None


def _kind(symbol: str) -> str:
    try:
        p = parse(symbol)
    except (ValueError, KeyError):
        return "equity"
    return "option" if p.is_option else "future" if p.is_future else "equity"


def analyze_positions(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """positions: {symbol, quantity, average_price, last_price, pnl?} (net qty, + long / - short)."""
    rows = []
    for p in positions:
        qty = int(p.get("quantity") or 0)
        if qty == 0:
            continue
        px = float(p.get("last_price") or p.get("average_price") or 0)
        rows.append({**p, "value": qty * px, "kind": _kind(p["symbol"]), "asset": _underlying_asset(p["symbol"])})
    gross = sum(abs(r["value"]) for r in rows)
    net = sum(r["value"] for r in rows)
    by_sector: dict[str, float] = defaultdict(float)
    by_kind: dict[str, float] = defaultdict(float)
    beta_num = 0.0
    for r in rows:
        a = r["asset"]
        sector = (a.sector if a and a.sector else "Index" if a and a.kind == "index" else "Other")
        by_sector[sector] += abs(r["value"])
        by_kind[r["kind"]] += abs(r["value"])
        beta_num += r["value"] * (a.beta if a else 1.0)
    weights = sorted(((r["symbol"], abs(r["value"]) / gross * 100 if gross else 0.0) for r in rows), key=lambda x: -x[1])
    hhi = round(sum((w / 100) ** 2 for _, w in weights), 4)
    short_options = [r for r in rows if r["kind"] == "option" and r["quantity"] < 0]
    long_options = [r for r in rows if r["kind"] == "option" and r["quantity"] > 0]
    obs: list[str] = []
    if weights and weights[0][1] > 40:
        obs.append(f"Concentration: {weights[0][0]} is {weights[0][1]:.0f}% of gross exposure.")
    if hhi > 0.25 and len(rows) > 1:
        obs.append(f"HHI {hhi:.2f} indicates a concentrated book (effective positions ≈ {1 / hhi:.1f}).")
    top_sector = max(by_sector.items(), key=lambda kv: kv[1]) if by_sector else None
    if top_sector and gross and top_sector[1] / gross > 0.5 and len(by_sector) > 1:
        obs.append(f"Over half of exposure is in {top_sector[0]}.")
    if short_options and not long_options:
        obs.append("Net short options without long hedges: loss is theoretically unlimited and margin-intensive.")
    if gross and abs(net) / gross < 0.2 and len(rows) > 1:
        obs.append("The book is close to market-neutral on a notional basis.")
    if not rows:
        obs.append("No open positions.")
    return {
        "positions": len(rows),
        "gross_exposure": round(gross, 2),
        "net_exposure": round(net, 2),
        "beta_weighted_exposure": round(beta_num, 2),
        "portfolio_beta": round(beta_num / net, 2) if net else None,
        "unrealised_pnl": round(sum(float(r.get("unrealised_pnl") or 0) for r in rows), 2),
        "concentration": {"top_symbol": weights[0][0] if weights else None, "top_weight_pct": round(weights[0][1], 1) if weights else 0,
                          "hhi": hhi},
        "weights": [{"symbol": s, "weight_pct": round(w, 2)} for s, w in weights],
        "by_sector": [{"sector": k, "value": round(v, 2), "weight_pct": round(v / gross * 100, 1) if gross else 0}
                      for k, v in sorted(by_sector.items(), key=lambda kv: -kv[1])],
        "by_instrument": [{"kind": k, "value": round(v, 2)} for k, v in by_kind.items()],
        "short_option_legs": len(short_options),
        "observations": obs,
    }


def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1) -> float | None:
    """Annualised money-weighted return. cashflows: (date, amount) with investments negative, current value positive."""
    if len(cashflows) < 2 or not any(c < 0 for _, c in cashflows) or not any(c > 0 for _, c in cashflows):
        return None
    t0 = min(d for d, _ in cashflows)

    def npv(r: float) -> float:
        return sum(c / (1 + r) ** ((d - t0).days / 365.0) for d, c in cashflows)

    def dnpv(r: float) -> float:
        return sum(-((d - t0).days / 365.0) * c / (1 + r) ** ((d - t0).days / 365.0 + 1) for d, c in cashflows)

    r = guess
    for _ in range(100):
        f, df = npv(r), dnpv(r)
        if abs(df) < 1e-12:
            break
        nr = r - f / df
        if nr <= -0.9999:
            nr = (r - 0.9999) / 2
        if abs(nr - r) < 1e-9:
            return round(nr * 100, 2)
        r = nr
    # fallback: bisection
    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2 * 100, 2)
