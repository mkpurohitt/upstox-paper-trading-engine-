"""Portfolio tools (read-only)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ai_agent.tools.registry import ToolContext, ToolResult, tool
from algo_db.session import session_scope
from broker_gateway.paper import PaperBroker
from market_data.registry import get_provider
from strategy_engine.analytics.portfolio import analyze_positions


class PortfolioArgs(BaseModel):
    mode: Literal["paper"] = "paper"


async def _positions(user_id: int) -> tuple[list[dict], dict, float]:  # type: ignore[type-arg]
    async with session_scope() as db:
        pb = PaperBroker(user_id, db, get_provider())
        pos = await pb.get_positions()
        funds = await pb.get_funds()
        day = await pb.day_pnl()
    rows = [{"symbol": p.symbol, "product": p.product.value if hasattr(p.product, "value") else p.product, "quantity": p.quantity,
             "average_price": round(p.average_price, 2), "last_price": round(p.last_price, 2),
             "unrealised_pnl": round(p.unrealised_pnl, 2), "realised_pnl": round(p.realised_pnl, 2)} for p in pos]
    return rows, {"available": round(funds.available, 2), "used_margin": round(funds.used, 2), "total": round(funds.total, 2)}, day


@tool("get_portfolio", "The user's paper-trading account: funds, open and closed positions with P&L, and today's P&L.", PortfolioArgs,
      category="portfolio")
async def get_portfolio(ctx: ToolContext, a: PortfolioArgs) -> ToolResult:
    rows, funds, day = await _positions(ctx.user_id)
    data = {"mode": a.mode, "funds": funds, "positions": rows[:50], "day_pnl": round(day, 2)}
    return ToolResult(data, {"type": "portfolio", **data})


@tool("analyze_portfolio", "Risk analysis of open positions: gross/net exposure, beta, concentration (top weight, HHI), sector and "
      "instrument mix, unhedged short options, with observations.", PortfolioArgs, category="portfolio")
async def analyze_portfolio(ctx: ToolContext, a: PortfolioArgs) -> ToolResult:
    rows, funds, day = await _positions(ctx.user_id)
    an = analyze_positions([r for r in rows if r["quantity"]])
    data = {"mode": a.mode, **an, "funds": funds, "day_pnl": round(day, 2)}
    return ToolResult(data, {"type": "portfolio_analysis", **data})
