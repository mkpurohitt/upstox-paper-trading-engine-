"""Pre-trade risk engine. Every order passes through `RiskEngine.evaluate`
before it can reach any broker (paper or live); every decision is audited.

Rules (evaluated in order, first failure rejects):

==========================  ==============================================================
kill_switch.global          platform-wide kill switch (env or admin toggle)
kill_switch.user            user's kill switch (topbar button / API)
kill_switch.strategy        per-strategy kill switch
live_requires_2fa           live orders need TOTP 2FA enabled on the account
exchange_allowed            exchange in the user's / strategy's allowed list
instrument_allowed          symbol matches allowed glob patterns (if configured)
max_qty_per_order           quantity cap per order
max_lots                    derivative lot cap per order
max_position_value          resulting position notional cap (risk-increasing orders)
orders_per_minute           sliding-window order count (user and strategy)
sebi_order_rate             < ORDER_RATE_LIMIT_PER_SEC per exchange per client (SEBI retail threshold 10/s)
max_loss_per_day            day P&L breach blocks new risk (exits still allowed)
price_band                  LIMIT/SL price within ±20% of LTP (fat-finger guard)
==========================  ==============================================================
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.metrics import RISK_DECISIONS
from algo_common.ratelimit import SlidingWindowLimiter
from algo_common.settings import get_settings
from algo_db.models import RiskLimit, SystemFlag, User
from broker_gateway.models import OrderRequest, Position, Side

GLOBAL_KILL_FLAG = "kill_switch.global"


@dataclass
class RiskCheck:
    rule: str
    passed: bool
    detail: str = ""


@dataclass
class RiskDecision:
    allowed: bool
    rule: str | None = None
    reason: str | None = None
    checks: list[RiskCheck] = field(default_factory=list)
    reducing: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "rule": self.rule, "reason": self.reason, "reducing": self.reducing,
                "checks": [{"rule": c.rule, "passed": c.passed, "detail": c.detail} for c in self.checks]}


@dataclass
class EffectiveLimits:
    max_loss_per_day: float
    max_orders_per_min: int
    max_position_value: float
    max_lots: int
    max_qty_per_order: int
    allowed_instruments: list[str]
    allowed_exchanges: list[str]
    kill_user: bool = False
    kill_strategy: bool = False


async def global_kill_engaged(db: AsyncSession) -> bool:
    if get_settings().global_kill_switch:
        return True
    flag = await db.get(SystemFlag, GLOBAL_KILL_FLAG)
    return bool(flag and flag.value.get("engaged"))


async def effective_limits(db: AsyncSession, user: User, strategy_id: int | None, overrides: dict[str, Any] | None = None) -> EffectiveLimits:
    rows = (await db.execute(select(RiskLimit).where(RiskLimit.user_id == user.id,
                                                     (RiskLimit.strategy_id.is_(None)) | (RiskLimit.strategy_id == strategy_id)))).scalars().all()
    base = next((r for r in rows if r.strategy_id is None), None) or RiskLimit(user_id=user.id)
    strat = next((r for r in rows if r.strategy_id == strategy_id and strategy_id is not None), None)

    def pick(name: str) -> Any:
        vals = [getattr(base, name)]
        if strat is not None and getattr(strat, name) is not None:
            vals.append(getattr(strat, name))
        if overrides and overrides.get(name) is not None:
            vals.append(overrides[name])
        vals = [v for v in vals if v is not None]
        return min(vals) if vals and isinstance(vals[0], int | float) else (vals[-1] if vals else None)

    defaults = RiskLimit()
    return EffectiveLimits(
        max_loss_per_day=float(pick("max_loss_per_day") or defaults.max_loss_per_day or 25_000),
        max_orders_per_min=int(pick("max_orders_per_min") or 60),
        max_position_value=float(pick("max_position_value") or 1_000_000),
        max_lots=int(pick("max_lots") or 10),
        max_qty_per_order=int(pick("max_qty_per_order") or 5000),
        allowed_instruments=list((strat.allowed_instruments if strat and strat.allowed_instruments else base.allowed_instruments) or []),
        allowed_exchanges=list(base.allowed_exchanges or ["NSE", "BSE", "NFO", "BFO", "MCX"]),
        kill_user=bool(user.kill_switch or base.kill_switch),
        kill_strategy=bool(strat.kill_switch) if strat else False,
    )


class RiskEngine:
    def __init__(self) -> None:
        s = get_settings()
        self.sebi_limiter = SlidingWindowLimiter(s.order_rate_limit_per_sec, 1.0, prefix="rl:sebi")
        self._minute: dict[int, SlidingWindowLimiter] = {}

    def _per_minute(self, limit: int) -> SlidingWindowLimiter:
        if limit not in self._minute:
            self._minute[limit] = SlidingWindowLimiter(limit, 60.0, prefix=f"rl:opm{limit}")
        return self._minute[limit]

    async def evaluate(
        self, db: AsyncSession, user: User, req: OrderRequest, *, mode: str, ltp: float | None, lot_size: int = 1,
        positions: list[Position] | None = None, day_pnl: float = 0.0, overrides: dict[str, Any] | None = None,
        bypass_kill: bool = False, record_rate: bool = True,
    ) -> RiskDecision:
        lim = await effective_limits(db, user, req.strategy_id, overrides)
        checks: list[RiskCheck] = []
        pos = next((p for p in positions or [] if p.symbol == req.symbol and p.product == req.product), None)
        reducing = pos is not None and pos.quantity != 0 and (
            (pos.quantity > 0 and req.side == Side.SELL) or (pos.quantity < 0 and req.side == Side.BUY)
        ) and req.quantity <= abs(pos.quantity)

        def check(rule: str, ok: bool, detail: str = "") -> bool:
            # `detail` describes the failure; recording it on a passing check would read as a violation in the audit
            checks.append(RiskCheck(rule, ok, "" if ok else detail))
            RISK_DECISIONS.labels("pass" if ok else "reject", rule).inc()
            return ok

        def reject(rule: str) -> RiskDecision:
            return RiskDecision(False, rule, checks[-1].detail, checks, reducing)

        if not bypass_kill:
            if not check("kill_switch.global", not await global_kill_engaged(db), "platform kill switch engaged"):
                return reject("kill_switch.global")
            if not check("kill_switch.user", not lim.kill_user, "your kill switch is engaged"):
                return reject("kill_switch.user")
            if not check("kill_switch.strategy", not lim.kill_strategy, "strategy kill switch engaged"):
                return reject("kill_switch.strategy")
        if mode == "live" and not check("live_requires_2fa", user.totp_enabled, "enable two-factor authentication to trade live"):
            return reject("live_requires_2fa")
        if not check("exchange_allowed", req.exchange in lim.allowed_exchanges, f"{req.exchange} not in {lim.allowed_exchanges}"):
            return reject("exchange_allowed")
        if lim.allowed_instruments:
            ok = any(fnmatch.fnmatchcase(req.symbol, pat) for pat in lim.allowed_instruments)
            if not check("instrument_allowed", ok, f"{req.symbol} not allowed by {lim.allowed_instruments}"):
                return reject("instrument_allowed")
        if not check("max_qty_per_order", req.quantity <= lim.max_qty_per_order, f"qty {req.quantity} > {lim.max_qty_per_order}"):
            return reject("max_qty_per_order")
        if lot_size > 1:
            if not check("lot_multiple", req.quantity % lot_size == 0, f"qty {req.quantity} is not a multiple of lot size {lot_size}"):
                return reject("lot_multiple")
            lots = req.quantity // lot_size
            if not check("max_lots", lots <= lim.max_lots, f"{lots} lots > {lim.max_lots}"):
                return reject("max_lots")
        price = req.price or ltp or 0.0
        if not reducing and price:
            existing = abs(pos.quantity) * (pos.last_price or pos.average_price) if pos else 0.0
            notional = existing + req.quantity * price
            if not check("max_position_value", notional <= lim.max_position_value,
                         f"position ₹{notional:,.0f} > ₹{lim.max_position_value:,.0f}"):
                return reject("max_position_value")
        if not reducing and not check("max_loss_per_day", day_pnl > -lim.max_loss_per_day,
                                      f"day P&L ₹{day_pnl:,.0f} breached -₹{lim.max_loss_per_day:,.0f}; only exits allowed"):
            return reject("max_loss_per_day")
        if ltp and req.price and req.order_type.value in ("LIMIT", "SL"):
            band = abs(req.price / ltp - 1)
            if not check("price_band", band <= 0.2, f"limit price {req.price} is {band:.0%} away from LTP {ltp}"):
                return reject("price_band")
        if record_rate:
            ok, n = await self._per_minute(lim.max_orders_per_min).hit(f"u{user.id}")
            if not check("orders_per_minute", ok, f"{n} orders in the last minute > {lim.max_orders_per_min}"):
                return reject("orders_per_minute")
            if req.strategy_id:
                ok, n = await self._per_minute(lim.max_orders_per_min).hit(f"s{req.strategy_id}")
                if not check("orders_per_minute.strategy", ok, f"strategy sent {n} orders in the last minute"):
                    return reject("orders_per_minute.strategy")
            ok, n = await self.sebi_limiter.hit(f"u{user.id}:{req.exchange}")
            if not check("sebi_order_rate", ok, f"{n} orders/sec on {req.exchange} exceeds {get_settings().order_rate_limit_per_sec}/s"):
                return reject("sebi_order_rate")
        return RiskDecision(True, None, None, checks, reducing)


_engine: RiskEngine | None = None


def get_risk_engine() -> RiskEngine:
    global _engine
    if _engine is None:
        _engine = RiskEngine()
    return _engine
