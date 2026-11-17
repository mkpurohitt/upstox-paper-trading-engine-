"""PaperBroker - fully simulated execution (the default broker).

* MARKET orders fill immediately at LTP (bid/ask aware) +/- slippage (bps), rounded to tick.
* LIMIT orders fill when marketable, otherwise rest as OPEN; SL / SL-M wait as
  TRIGGER_PENDING. `PaperMatcher` re-checks resting orders against live prices.
* Positions, P&L and funds are derived from the paper trade ledger in the DB,
  so the paper account survives restarts and is visible in Portfolio.
* Margin model (approximate): MIS equity 20% of notional, CNC 100%, futures
  ~15%, option buy = premium, option sell ~15% of underlying notional.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.logging import get_logger
from algo_common.settings import get_settings
from algo_common.timeutils import IST, now_ist, utcnow
from algo_db.models import Order as OrderRow
from algo_db.models import Trade as TradeRow
from broker_gateway.base import BrokerAdapter, BrokerError
from broker_gateway.models import (
    Funds,
    Holding,
    ModifyRequest,
    Order,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Product,
    Profile,
    Side,
    Trade,
)
from market_data.base import MarketDataProvider
from market_data.symbols import parse

log = get_logger("paper")
MIS_SQUARE_OFF = time(15, 20)


def _tick(price: float, tick: float = 0.05) -> float:
    return round(round(price / tick) * tick, 2)


def margin_for(symbol: str, product: str, side: str, qty: int, price: float, underlying_price: float | None = None) -> float:
    p = parse(symbol)
    notional = abs(qty * price)
    if p.is_option:
        if side == "BUY":
            return notional
        return abs(qty * (underlying_price or price * 20)) * 0.15
    if p.is_future:
        return notional * 0.15
    return notional * (0.2 if product == "MIS" else 1.0)


class PaperBroker(BrokerAdapter):
    name = "paper"
    display_name = "Paper trading (simulated)"
    auth_type = "none"
    rate_limit_per_sec = 50.0

    def __init__(self, user_id: int, db: AsyncSession, provider: MarketDataProvider | None = None,
                 slippage_bps: float | None = None) -> None:
        super().__init__({}, {})
        from market_data.registry import get_provider

        self.user_id = user_id
        self.db = db
        self.provider = provider or get_provider()
        self.slippage_bps = get_settings().paper_slippage_bps if slippage_bps is None else slippage_bps

    # ---- pricing ----------------------------------------------------------------
    async def _quote(self, symbol: str) -> tuple[float, float | None, float | None]:
        q = (await self.provider.quotes([symbol])).get(symbol)
        if q is None or not q.ltp:
            raise BrokerError(f"No price for {symbol}; cannot simulate a fill")
        return q.ltp, q.bid, q.ask

    def _fill_price(self, side: Side, ltp: float, bid: float | None, ask: float | None) -> float:
        base = (ask or ltp) if side == Side.BUY else (bid or ltp)
        slip = base * self.slippage_bps / 1e4
        return max(0.05, _tick(base + slip if side == Side.BUY else base - slip))

    @staticmethod
    def would_fill(order_type: OrderType, side: Side, ltp: float, price: float | None, trigger: float | None) -> tuple[bool, bool]:
        """(triggered, fills_now) for a resting order at the current LTP."""
        if order_type in (OrderType.SL, OrderType.SL_M):
            assert trigger is not None
            triggered = ltp >= trigger if side == Side.BUY else ltp <= trigger
            if not triggered:
                return False, False
            if order_type == OrderType.SL_M:
                return True, True
            assert price is not None
            return True, (ltp <= price if side == Side.BUY else ltp >= price)
        if order_type == OrderType.LIMIT:
            assert price is not None
            return True, (ltp <= price if side == Side.BUY else ltp >= price)
        return True, True

    # ---- orders -------------------------------------------------------------------
    async def place_order(self, req: OrderRequest) -> OrderAck:
        ltp, bid, ask = await self._quote(req.symbol)
        oid = f"PAPER-{uuid.uuid4().hex[:12].upper()}"
        # funds check for risk-increasing orders
        funds = await self.get_funds()
        pos = {(p.symbol, p.product): p for p in await self.get_positions()}.get((req.symbol, req.product))
        reducing = pos is not None and ((pos.quantity > 0 and req.side == Side.SELL) or (pos.quantity < 0 and req.side == Side.BUY)) \
            and req.quantity <= abs(pos.quantity)
        if not reducing:
            need = margin_for(req.symbol, req.product.value, req.side.value, req.quantity, req.price or ltp)
            if need > funds.available + 1e-6:
                return OrderAck(broker_order_id=oid, status=OrderStatus.REJECTED,
                                message=f"Insufficient paper funds: need ₹{need:,.0f}, available ₹{funds.available:,.0f}")
        triggered, fills = self.would_fill(req.order_type, req.side, ltp, req.price, req.trigger_price)
        if not fills:
            return OrderAck(broker_order_id=oid, status=OrderStatus.OPEN if triggered else OrderStatus.TRIGGER_PENDING,
                            message="resting")
        px = self._fill_price(req.side, ltp, bid, ask)
        if req.order_type in (OrderType.LIMIT, OrderType.SL) and req.price:
            px = min(px, req.price) if req.side == Side.BUY else max(px, req.price)
        return OrderAck(broker_order_id=oid, status=OrderStatus.COMPLETE, filled_quantity=req.quantity, average_price=px,
                        message="filled (simulated)")

    async def _row(self, broker_order_id: str) -> OrderRow:
        row = (await self.db.execute(select(OrderRow).where(OrderRow.broker_order_id == broker_order_id,
                                                            OrderRow.user_id == self.user_id))).scalar_one_or_none()
        if row is None:
            raise BrokerError("Paper order not found")
        return row

    async def modify_order(self, broker_order_id: str, req: ModifyRequest, original: Order | None = None) -> OrderAck:
        row = await self._row(broker_order_id)
        if OrderStatus(row.status).is_terminal:
            raise BrokerError(f"Order is already {row.status}")
        if req.quantity:
            row.quantity = req.quantity
        if req.price is not None:
            row.price = req.price
        if req.trigger_price is not None:
            row.trigger_price = req.trigger_price
        if req.order_type:
            row.order_type = req.order_type.value
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus(row.status))

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        row = await self._row(broker_order_id)
        if OrderStatus(row.status).is_terminal:
            raise BrokerError(f"Order is already {row.status}")
        return OrderAck(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    # ---- books (derived from the DB ledger) ------------------------------------------
    async def get_order_book(self) -> list[Order]:
        start = datetime.combine(now_ist().date(), time(0, 0), tzinfo=IST)
        rows = (await self.db.execute(select(OrderRow).where(OrderRow.user_id == self.user_id, OrderRow.mode == "paper",
                                                             OrderRow.created_at >= start).order_by(OrderRow.id))).scalars()
        return [Order(broker_order_id=r.broker_order_id or r.client_order_id, symbol=r.symbol, side=Side(r.side),
                      quantity=r.quantity, filled_quantity=r.filled_quantity, price=r.price, trigger_price=r.trigger_price,
                      average_price=r.average_price, order_type=OrderType(r.order_type), product=Product(r.product),
                      status=OrderStatus(r.status), status_message=r.status_message, tag=r.tag, ts=r.created_at) for r in rows]

    async def get_trade_book(self) -> list[Trade]:
        rows = (await self.db.execute(select(TradeRow).where(TradeRow.user_id == self.user_id, TradeRow.mode == "paper")
                                      .order_by(TradeRow.ts))).scalars()
        return [Trade(broker_trade_id=str(r.id), broker_order_id=str(r.order_id), symbol=r.symbol, side=Side(r.side),
                      quantity=r.quantity, price=r.price, product=Product(r.product), ts=r.ts) for r in rows]

    async def _ledger(self, realised_since: datetime | None = None) -> dict[tuple[str, str], dict[str, float]]:
        """Average-cost ledger per (symbol, product). With `realised_since`, realised
        P&L and charges only count trades on/after that instant (used for day P&L)."""
        rows = (await self.db.execute(select(TradeRow).where(TradeRow.user_id == self.user_id, TradeRow.mode == "paper")
                                      .order_by(TradeRow.ts, TradeRow.id))).scalars()
        book: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"qty": 0.0, "avg": 0.0, "realised": 0.0, "charges": 0.0})
        for t in rows:
            b = book[(t.symbol, t.product)]
            signed = t.quantity if t.side == "BUY" else -t.quantity
            q, avg = b["qty"], b["avg"]
            counts = realised_since is None or t.ts >= realised_since
            if counts:
                b["charges"] += t.charges
            if q == 0 or (q > 0) == (signed > 0):
                b["avg"] = (avg * abs(q) + t.price * abs(signed)) / (abs(q) + abs(signed))
                b["qty"] = q + signed
            else:
                closing = min(abs(q), abs(signed))
                if counts:
                    b["realised"] += (t.price - avg) * closing * (1 if q > 0 else -1)
                b["qty"] = q + signed
                if abs(signed) > abs(q):  # flipped
                    b["avg"] = t.price
                elif b["qty"] == 0:
                    b["avg"] = 0.0
        return book

    async def get_positions(self, include_closed: bool = True) -> list[Position]:
        book = await self._ledger()
        open_syms = [s for (s, _), b in book.items() if b["qty"] != 0]
        quotes = await self.provider.quotes(open_syms) if open_syms else {}
        out = []
        for (sym, prod), b in book.items():
            if not include_closed and b["qty"] == 0:
                continue
            last = quotes[sym].ltp if sym in quotes else b["avg"]
            out.append(Position(symbol=sym, product=Product(prod), quantity=int(b["qty"]), average_price=round(b["avg"], 4),
                                last_price=last, realised_pnl=round(b["realised"] - b["charges"], 2),
                                unrealised_pnl=round((last - b["avg"]) * b["qty"], 2), broker="paper"))
        return out

    async def day_pnl(self) -> float:
        """Today's realised (net of charges) + unrealised P&L - feeds the daily loss limit."""
        start = datetime.combine(now_ist().date(), time(0, 0), tzinfo=IST)
        book = await self._ledger(realised_since=start)
        open_syms = [s for (s, _), b in book.items() if b["qty"] != 0]
        quotes = await self.provider.quotes(open_syms) if open_syms else {}
        total = 0.0
        for (sym, _), b in book.items():
            total += b["realised"] - b["charges"]
            if b["qty"] and sym in quotes:
                total += (quotes[sym].ltp - b["avg"]) * b["qty"]
        return round(total, 2)

    async def get_holdings(self) -> list[Holding]:
        return [Holding(symbol=p.symbol, quantity=p.quantity, average_price=p.average_price, last_price=p.last_price,
                        pnl=p.unrealised_pnl, broker="paper")
                for p in await self.get_positions() if p.product == Product.CNC and p.quantity > 0]

    async def get_funds(self) -> Funds:
        capital = get_settings().paper_starting_capital
        positions = await self.get_positions()
        realised = sum(p.realised_pnl for p in positions)
        unreal = sum(p.unrealised_pnl for p in positions)
        used = sum(margin_for(p.symbol, p.product.value, "BUY" if p.quantity > 0 else "SELL", abs(p.quantity), p.last_price or p.average_price)
                   for p in positions if p.quantity)
        total = capital + realised + unreal
        return Funds(available=round(total - used, 2), used=round(used, 2), total=round(total, 2))

    async def get_profile(self) -> Profile:
        return Profile(user_id=f"PAPER-{self.user_id}", name="Paper account", broker="paper", exchanges=["NSE", "BSE", "NFO", "BFO", "MCX"])


class PaperMatcher:
    """Fills resting paper orders when prices cross, and squares off MIS at 15:20 IST."""

    def __init__(self, provider: MarketDataProvider | None = None, interval_s: float = 1.0,
                 clock: Callable[[], datetime] | None = None) -> None:
        from market_data.registry import get_provider

        self.provider = provider or get_provider()
        self.interval = interval_s
        self.clock = clock or now_ist  # injectable for tests (MIS auto square-off is time-of-day dependent)
        self._squared_off_on: set[Any] = set()

    async def step(self) -> int:
        from algo_db.session import session_scope
        from broker_gateway.router import OrderRouter

        filled = 0
        async with session_scope() as db:
            rows = (await db.execute(select(OrderRow).where(OrderRow.mode == "paper",
                                                            OrderRow.status.in_(("open", "trigger_pending"))))).scalars().all()
            if rows:
                quotes = await self.provider.quotes(sorted({r.symbol for r in rows}))
                router = OrderRouter()
                for r in rows:
                    q = quotes.get(r.symbol)
                    if q is None:
                        continue
                    triggered, fills = PaperBroker.would_fill(OrderType(r.order_type), Side(r.side), q.ltp, r.price, r.trigger_price)
                    if triggered and r.status == "trigger_pending" and not fills:
                        r.status = "open"
                    if fills:
                        broker = PaperBroker(r.user_id, db, self.provider)
                        px = broker._fill_price(Side(r.side), q.ltp, q.bid, q.ask)
                        if r.order_type in ("LIMIT", "SL") and r.price:
                            px = min(px, r.price) if r.side == "BUY" else max(px, r.price)
                        await router.record_fill(db, r, r.quantity - r.filled_quantity, px)
                        filled += 1
        now = self.clock()
        if now.time() >= MIS_SQUARE_OFF and now.date() not in self._squared_off_on and now.weekday() < 5:
            await self.square_off_mis()
            self._squared_off_on.add(now.date())
        return filled

    async def square_off_mis(self) -> None:
        from algo_db.session import session_scope
        from broker_gateway.router import OrderRouter

        async with session_scope() as db:
            users = (await db.execute(select(TradeRow.user_id).where(TradeRow.mode == "paper", TradeRow.product == "MIS").distinct())).scalars().all()
            for uid in users:
                broker = PaperBroker(uid, db, self.provider)
                for p in await broker.get_positions(include_closed=False):
                    if p.product == Product.MIS and p.quantity:
                        req = OrderRequest(symbol=p.symbol, side=Side.SELL if p.quantity > 0 else Side.BUY, quantity=abs(p.quantity),
                                           product=Product.MIS, tag="auto-sqoff")
                        try:
                            await OrderRouter().place(db, uid, req, mode="paper", bypass_risk=True, actor="system")
                        except Exception as exc:
                            log.warning("paper.squareoff_failed", user=uid, symbol=p.symbol, error=str(exc))

    async def run(self) -> None:
        while True:
            try:
                await self.step()
            except Exception as exc:
                log.warning("paper.matcher_error", error=str(exc))
            await asyncio.sleep(self.interval)


__all__ = ["PaperBroker", "PaperMatcher", "margin_for", "utcnow"]
