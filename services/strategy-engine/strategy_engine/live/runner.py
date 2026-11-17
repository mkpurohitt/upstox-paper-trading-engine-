"""Per-deployment live strategy runner.

The runner executes the *same* DSL as the backtester:
* bars are built from live ticks (`BarBuilder`), appended to a warm-up history,
  and `generate_signals` is evaluated on bar close;
* stops / targets / trailing stops are checked on every tick (market exit);
* MIS positions are squared off at `schedule.square_off`;
* every order goes through `OrderRouter` (risk engine -> broker), tagged with
  the deployment's strategy id and Algo-ID;
* mode ``notify`` sends alerts instead of orders.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, time, timedelta
from typing import Any

import pandas as pd

from algo_common.bus import get_bus
from algo_common.errors import RiskRejectedError
from algo_common.logging import get_logger
from algo_common.schemas.market import Interval
from algo_common.timeutils import IST, expiry_from_date, now_ist, upcoming_expiries, utcnow
from algo_db.models import Deployment, DeploymentLog
from algo_db.session import session_scope
from broker_gateway.base import BrokerError
from broker_gateway.models import OrderRequest, Product, Side
from broker_gateway.notify import notify
from broker_gateway.router import OrderRouter
from market_data.base import MarketDataProvider
from market_data.options import atm_strike, strike_step
from market_data.symbols import option_symbol
from strategy_engine.backtest.pairs import rolling_hedge, spread_zscore
from strategy_engine.data import candles_to_frame
from strategy_engine.dsl import StrategyDSL
from strategy_engine.live.bars import Bar, BarBuilder
from strategy_engine.signals import generate_signals, warmup_bars

log = get_logger("runner")
_DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}


def _hhmm(s: str | None) -> time | None:
    if not s:
        return None
    h, m = s.split(":")
    return time(int(h), int(m))


class StrategyRunner:
    def __init__(self, deployment_id: int, provider: MarketDataProvider, router: OrderRouter | None = None) -> None:
        self.deployment_id = deployment_id
        self.provider = provider
        self.router = router or OrderRouter(provider)
        self.dsl: StrategyDSL | None = None
        self.user_id = 0
        self.strategy_id: int | None = None
        self.mode = "paper"
        self.connection_id: int | None = None
        self.multiplier = 1
        self.risk_overrides: dict[str, Any] = {}
        self.frames: dict[str, pd.DataFrame] = {}
        self.builders: dict[str, BarBuilder] = {}
        self.state: dict[str, Any] = {"positions": {}, "day": None, "trades_today": 0, "sl_hits": {}, "option_set": None}
        self.paused = False
        self._task: asyncio.Task[None] | None = None
        self._tick_symbols: set[str] = set()

    # ---- lifecycle -----------------------------------------------------------------
    async def load(self) -> None:
        async with session_scope() as db:
            d = await db.get(Deployment, self.deployment_id)
            if d is None:
                raise BrokerError("deployment not found")
            self.dsl = StrategyDSL.model_validate(d.dsl)
            self.user_id, self.strategy_id, self.mode = d.user_id, d.strategy_id, d.mode
            self.connection_id, self.multiplier = d.broker_connection_id, max(1, d.multiplier)
            self.risk_overrides = dict(d.risk_limits or {})
            self.state.update(d.state or {})
            self.paused = d.status == "paused"
        dsl = self.dsl
        end = utcnow()
        tf = dsl.timeframe
        days = {"1m": 5, "3m": 7, "5m": 10, "15m": 25, "30m": 40, "1h": 80, "1d": 900}[tf]
        n = warmup_bars(dsl)
        for sym in dsl.symbols:
            candles = await self.provider.candles(sym, Interval(tf), end - timedelta(days=days), end)
            self.frames[sym] = candles_to_frame(candles).tail(max(n, 300))
            self.builders[sym] = BarBuilder(tf)
        self._tick_symbols = set(dsl.symbols)
        await self.log("info", f"Runner started ({self.mode}) on {', '.join(dsl.symbols)} [{tf}]")

    async def log(self, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        async with session_scope() as db:
            db.add(DeploymentLog(deployment_id=self.deployment_id, level=level, message=message[:2000], data=data or {}))
        await get_bus().publish(f"deploy:{self.user_id}", {"type": "log", "deployment_id": self.deployment_id, "level": level,
                                                           "message": message, "ts": utcnow().isoformat(), "data": data or {}})

    async def persist(self, **fields: Any) -> None:
        async with session_scope() as db:
            d = await db.get(Deployment, self.deployment_id)
            if d is None:
                return
            d.state = dict(self.state)
            d.last_heartbeat = utcnow()
            for k, v in fields.items():
                setattr(d, k, v)

    # ---- order helpers -----------------------------------------------------------------
    async def order(self, symbol: str, side: Side, qty: int, reason: str) -> float | None:
        """Place a market order (or alert in notify mode). Returns the fill price when known."""
        assert self.dsl is not None
        ltp = None
        q = (await self.provider.quotes([symbol])).get(symbol)
        if q:
            ltp = q.ltp
        if self.mode == "notify":
            async with session_scope() as db:
                await notify(db, self.user_id, f"{self.dsl.name}: {side.value} {qty} {symbol}",
                             f"Signal ({reason}) at ~{ltp}. Notify-only mode: no order was placed.", kind="strategy",
                             data={"deployment_id": self.deployment_id, "symbol": symbol, "side": side.value, "qty": qty})
            await self.log("signal", f"{side.value} {qty} {symbol} ({reason}) @ ~{ltp}")
            return ltp
        product = Product(self.dsl.product)
        req = OrderRequest(symbol=symbol, side=side, quantity=qty, product=product, tag=f"D{self.deployment_id}",
                           strategy_id=self.strategy_id, deployment_id=self.deployment_id)
        try:
            async with session_scope() as db:
                rows = await self.router.place(db, self.user_id, req, mode=self.mode, connection_id=self.connection_id,
                                               actor="runner", overrides=self.risk_overrides)
            filled = [r for r in rows if r.status == "complete" and r.average_price]
            px = filled[0].average_price if filled else ltp
            await self.log("order", f"{side.value} {qty} {symbol} ({reason}) -> {rows[-1].status} @ {px}")
            return px
        except RiskRejectedError as exc:
            await self.log("risk", f"Risk rejected {side.value} {qty} {symbol}: {exc.message}", exc.details)
            return None
        except BrokerError as exc:
            await self.log("error", f"Order failed {side.value} {qty} {symbol}: {exc.message}")
            return None

    def _qty(self, symbol: str, price: float) -> int:
        assert self.dsl is not None
        s = self.dsl.sizing
        from market_data.symbols import parse
        from market_data.universe import asset_for_underlying

        lot = 1
        p = parse(symbol)
        if p.is_derivative and p.underlying:
            a = asset_for_underlying(p.underlying)
            lot = (a.lot_size if a and a.lot_size else 1)
        if s.mode == "fixed_qty":
            q = int(s.value)
        elif s.mode == "fixed_lots":
            q = int(s.value) * lot
        else:
            capital = float(self.risk_overrides.get("capital", 1_000_000))
            notional = capital * s.value / 100 if s.mode == "capital_pct" else s.value
            q = int(notional / max(price, 0.01) / lot) * lot
        return max(lot, q) * self.multiplier

    # ---- tick / bar handling -------------------------------------------------------------
    def _new_day(self, d: Any) -> None:
        if self.state.get("day") != str(d):
            self.state.update(day=str(d), trades_today=0, sl_hits={})

    async def on_tick(self, symbol: str, ltp: float, ts: datetime, cum_volume: float | None = None) -> None:
        if self.dsl is None or self.paused:
            return
        self._new_day(ts.astimezone(IST).date())
        if symbol in self.builders:
            bar = self.builders[symbol].on_tick(ts, ltp, cum_volume)
            if bar is not None:
                await self.on_bar(symbol, bar)
        if self.dsl.kind == "options":
            await self._options_tick(ts)
            return
        pos = self.state["positions"].get(symbol)
        if pos:
            await self._check_stops(symbol, pos, ltp, ts)

    async def _check_stops(self, symbol: str, pos: dict[str, Any], ltp: float, ts: datetime) -> None:
        assert self.dsl is not None
        side = pos["side"]
        pos["best"] = max(pos.get("best", ltp), ltp) if side > 0 else min(pos.get("best", ltp), ltp)
        tr = self.dsl.exit.trailing_sl
        if tr is not None:
            profit = (pos["best"] - pos["entry"]) * side
            trigger = tr.activate_after * (pos["entry"] / 100 if tr.type == "percent" else 1)
            if profit >= trigger:
                dist = pos["best"] * tr.value / 100 if tr.type == "percent" else tr.value
                ns = pos["best"] - side * dist
                if pos.get("stop") is None or (ns - pos["stop"]) * side > 0:
                    pos["stop"] = ns
        reason = None
        if pos.get("stop") is not None and ((side > 0 and ltp <= pos["stop"]) or (side < 0 and ltp >= pos["stop"])):
            reason = "stop_loss"
        elif pos.get("target") is not None and ((side > 0 and ltp >= pos["target"]) or (side < 0 and ltp <= pos["target"])):
            reason = "target"
        sq = _hhmm(self.dsl.schedule.square_off) if self.dsl.product == "MIS" else None
        if reason is None and sq and ts.astimezone(IST).time() >= sq:
            reason = "square_off"
        if reason:
            await self._exit(symbol, reason)

    async def _exit(self, symbol: str, reason: str) -> None:
        pos = self.state["positions"].pop(symbol, None)
        if not pos:
            return
        await self.order(symbol, Side.SELL if pos["side"] > 0 else Side.BUY, pos["qty"], reason)
        if reason == "stop_loss":
            self.state["sl_hits"][symbol] = self.state["sl_hits"].get(symbol, 0) + 1
        await self.persist()

    def _in_window(self, ts: datetime) -> bool:
        assert self.dsl is not None
        t = ts.astimezone(IST)
        sch = self.dsl.schedule
        if t.weekday() not in {_DAYS[d] for d in sch.days}:
            return False
        a, b = _hhmm(sch.entry_after), _hhmm(sch.entry_before)
        return (a is None or t.time() >= a) and (b is None or t.time() < b)

    def _can_enter(self, symbol: str) -> bool:
        assert self.dsl is not None
        r = self.dsl.risk
        if r.max_trades_per_day and self.state["trades_today"] >= r.max_trades_per_day:
            return False
        sl = self.state["sl_hits"].get(symbol, 0)
        return not (sl and (not self.dsl.reentry.enabled or sl > self.dsl.reentry.max_per_day))

    async def on_bar(self, symbol: str, bar: Bar) -> None:
        assert self.dsl is not None
        row = pd.DataFrame({"open": [bar.open], "high": [bar.high], "low": [bar.low], "close": [bar.close],
                            "volume": [bar.volume]}, index=pd.DatetimeIndex([pd.Timestamp(bar.ts).tz_convert("UTC")]))
        frame = self.frames.get(symbol)
        frame = row if frame is None or frame.empty else pd.concat([frame[frame.index < row.index[0]], row]).tail(1500)
        self.frames[symbol] = frame
        if self.paused:
            return
        if self.dsl.kind == "pair":
            await self._pair_bar()
            return
        if self.dsl.kind == "options":
            await self._options_entry(bar.ts)
            return
        sig = generate_signals(frame, self.dsl).iloc[-1]
        pos = self.state["positions"].get(symbol)
        if pos:
            if (pos["side"] > 0 and (sig["exit_long"] or sig["entry_short"])) or (pos["side"] < 0 and (sig["exit_short"] or sig["entry_long"])):
                await self._exit(symbol, "signal")
            return
        if not self._in_window(bar.ts + timedelta(minutes=self.builders[symbol].minutes)) or not self._can_enter(symbol):
            return
        if bool(sig["entry_long"]) == bool(sig["entry_short"]):
            return
        side = 1 if sig["entry_long"] else -1
        qty = self._qty(symbol, bar.close)
        px = await self.order(symbol, Side.BUY if side > 0 else Side.SELL, qty, "entry signal")
        if px is None:
            return
        stop = target = None
        ex = self.dsl.exit
        if ex.stop_loss and ex.stop_loss.type in ("percent", "points"):
            d = px * ex.stop_loss.value / 100 if ex.stop_loss.type == "percent" else ex.stop_loss.value
            stop = px - side * d
        if ex.target and ex.target.type in ("percent", "points"):
            d = px * ex.target.value / 100 if ex.target.type == "percent" else ex.target.value
            target = px + side * d
        self.state["positions"][symbol] = {"side": side, "qty": qty, "entry": px, "stop": stop, "target": target, "best": px,
                                           "ts": bar.ts.isoformat()}
        self.state["trades_today"] += 1
        await self.persist()

    # ---- options ----------------------------------------------------------------------------
    async def _options_entry(self, ts: datetime) -> None:
        assert self.dsl is not None
        if self.state.get("option_set") or not self._in_window(ts) or not self._can_enter("SET"):
            return
        und = (self.dsl.universe.underlying or "NIFTY").upper()
        if self.dsl.entry.long is not None:
            frame = self.frames.get(self.dsl.symbols[0])
            if frame is None or frame.empty or not bool(generate_signals(frame, self.dsl)["entry_long"].iloc[-1]):
                return
        legs = []
        for spec in self.dsl.legs:
            if spec.option_type == "FUT":
                continue
            exch = "BSE" if und in ("SENSEX", "BANKEX") else "NSE"
            exps = upcoming_expiries(und if spec.expiry != "monthly" else "_MONTHLY_", expiry_from_date(now_ist(), exch), 2, exch)
            expiry = exps[1] if spec.expiry == "next" else exps[0]
            chain = await self.provider.option_chain(und, expiry, 25)
            step = strike_step(und, chain.spot)
            if spec.strike.mode == "ATM_OFFSET":
                strike = atm_strike(chain.spot, step) + spec.strike.offset * step
            else:
                def score(r: Any, spec: Any = spec) -> float:
                    leg = r.call if spec.option_type == "CE" else r.put
                    if leg is None:
                        return 1e9
                    if spec.strike.mode == "DELTA":
                        return abs(abs(leg.greeks.delta) - (spec.strike.delta or 0.25))
                    return abs(leg.ltp - (spec.strike.premium or 50))
                strike = min(chain.rows, key=score).strike
            sym = option_symbol(und, expiry, strike, spec.option_type)
            qty = spec.lots * chain.lot_size * self.multiplier
            side = Side.BUY if spec.action == "BUY" else Side.SELL
            px = await self.order(sym, side, qty, f"leg {spec.id}")
            if px is None:
                await self.log("error", "Leg failed - unwinding the set")
                for lg in legs:
                    await self.order(lg["symbol"], Side.SELL if lg["sign"] > 0 else Side.BUY, lg["qty"], "unwind")
                return
            legs.append({"id": spec.id, "symbol": sym, "qty": qty, "sign": 1 if side == Side.BUY else -1, "entry": px,
                         "sl_pct": spec.stop_loss_pct, "open": True})
        if legs:
            self.state["option_set"] = {"legs": legs, "credit": sum(-lg["sign"] * lg["entry"] for lg in legs)}
            self.state["trades_today"] += 1
            self._tick_symbols |= {lg["symbol"] for lg in legs}
            await self.persist()

    async def _options_tick(self, ts: datetime) -> None:
        assert self.dsl is not None
        s = self.state.get("option_set")
        if not s:
            return
        legs = [lg for lg in s["legs"] if lg["open"]]
        quotes = await self.provider.quotes([lg["symbol"] for lg in legs])
        mtm = 0.0
        for lg in s["legs"]:
            last = quotes[lg["symbol"]].ltp if lg["symbol"] in quotes else lg.get("exit", lg["entry"])
            mtm += (last - lg["entry"]) * lg["qty"] * lg["sign"]
            if lg["open"] and lg.get("sl_pct") and lg["sign"] < 0 and last >= lg["entry"] * (1 + lg["sl_pct"] / 100):
                await self.order(lg["symbol"], Side.BUY, lg["qty"], f"leg SL {lg['id']}")
                lg["open"], lg["exit"] = False, last
        ox = self.dsl.options_exit
        qty = legs[0]["qty"] if legs else 0
        reason = None
        if ox.stop_loss_amount and mtm <= -ox.stop_loss_amount:
            reason = "stop_loss"
        elif ox.combined_stop_loss_pct and qty and mtm <= -abs(s["credit"]) * qty * ox.combined_stop_loss_pct / 100:
            reason = "stop_loss"
        elif ox.target_amount and mtm >= ox.target_amount:
            reason = "target"
        elif ox.combined_target_pct and qty and mtm >= abs(s["credit"]) * qty * ox.combined_target_pct / 100:
            reason = "target"
        sq = _hhmm(self.dsl.schedule.square_off)
        if reason is None and sq and self.dsl.product == "MIS" and ts.astimezone(IST).time() >= sq:
            reason = "square_off"
        if reason or not any(lg["open"] for lg in s["legs"]):
            for lg in s["legs"]:
                if lg["open"]:
                    await self.order(lg["symbol"], Side.BUY if lg["sign"] < 0 else Side.SELL, lg["qty"], reason or "legs closed")
                    lg["open"] = False
            await self.log("info", f"Option set closed ({reason or 'legs closed'}), MTM ₹{mtm:,.0f}")
            if reason == "stop_loss":
                self.state["sl_hits"]["SET"] = self.state["sl_hits"].get("SET", 0) + 1
            self.state["option_set"] = None
            await self.persist()

    # ---- pairs --------------------------------------------------------------------------------
    async def _pair_bar(self) -> None:
        assert self.dsl is not None and self.dsl.pair is not None
        ps = self.dsl.pair
        a, b = self.frames.get(ps.leg_a), self.frames.get(ps.leg_b)
        if a is None or b is None or len(a) < ps.lookback + 2 or len(b) < ps.lookback + 2:
            return
        df = pd.concat({"a": a["close"], "b": b["close"]}, axis=1).dropna()
        beta = rolling_hedge(df["a"], df["b"], ps.lookback) if ps.hedge == "ols" else pd.Series(ps.fixed_ratio or 1.0, index=df.index)
        _, z = spread_zscore(df["a"], df["b"], ps.lookback, beta)
        zi, bi = float(z.iloc[-1]), float(beta.iloc[-1])
        pos = self.state["positions"].get("PAIR")
        if pos:
            if abs(zi) <= ps.exit_z or (ps.stop_z and abs(zi) >= ps.stop_z):
                s = pos["side"]
                await self.order(ps.leg_a, Side.SELL if s > 0 else Side.BUY, pos["qa"], "pair exit")
                await self.order(ps.leg_b, Side.BUY if s > 0 else Side.SELL, pos["qb"], "pair exit")
                self.state["positions"].pop("PAIR")
                await self.persist()
            return
        if abs(zi) >= ps.entry_z and (not ps.stop_z or abs(zi) < ps.stop_z):
            s = -1 if zi > 0 else 1
            pa, pb = float(df["a"].iloc[-1]), float(df["b"].iloc[-1])
            notional = float(self.risk_overrides.get("capital", 1_000_000)) * self.dsl.sizing.value / 100 / 2
            qa, qb = max(1, int(notional / pa)) * self.multiplier, max(1, int(notional * abs(bi) / pb)) * self.multiplier
            await self.order(ps.leg_a, Side.BUY if s > 0 else Side.SELL, qa, f"pair entry z={zi:.2f}")
            await self.order(ps.leg_b, Side.SELL if s > 0 else Side.BUY, qb, f"pair entry z={zi:.2f}")
            self.state["positions"]["PAIR"] = {"side": s, "qa": qa, "qb": qb, "z": zi}
            await self.persist()

    # ---- driver ----------------------------------------------------------------------------------
    async def run(self) -> None:
        await self.load()
        bus = get_bus()
        pnl_every = 5.0
        last_pnl = 0.0
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=10_000)

        async def pump() -> None:
            # cancelling an async generator's __anext__ would close it, so drain it in its own task
            async for ch, msg in bus.subscribe("ticks:*"):
                if ch.split(":", 1)[1] in self._tick_symbols:
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait((ch, msg))

        pump_task = asyncio.create_task(pump(), name=f"runner-pump:{self.deployment_id}")
        try:
            while True:
                try:
                    ch, msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                    sym = ch.split(":", 1)[1]
                    ts = datetime.fromisoformat(msg["ts"]) if msg.get("ts") else utcnow()
                    await self.on_tick(sym, float(msg["ltp"]), ts, msg.get("volume"))
                except TimeoutError:
                    pass
                if pump_task.done():
                    raise RuntimeError("tick subscription ended unexpectedly") from pump_task.exception()
                now = utcnow()
                for sym, b in self.builders.items():
                    bar = b.flush_if_due(now)
                    if bar is not None:
                        await self.on_bar(sym, bar)
                if loop.time() - last_pnl >= pnl_every:
                    last_pnl = loop.time()
                    await self.publish_pnl()
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pump_task

    async def publish_pnl(self) -> None:
        from sqlalchemy import select

        from algo_db.models import Trade

        async with session_scope() as db:
            trades = (await db.execute(select(Trade).where(Trade.deployment_id == self.deployment_id)
                                       .order_by(Trade.ts, Trade.id))).scalars().all()
        open_syms = sorted({t.symbol for t in trades})
        quotes = await self.provider.quotes(open_syms) if open_syms else {}
        realised, unrealised, n_open = ledger_pnl(trades, {k: v.ltp for k, v in quotes.items()})
        await self.persist(pnl_realised=realised, pnl_unrealised=unrealised)
        await get_bus().publish(f"deploy:{self.user_id}", {
            "type": "pnl", "deployment_id": self.deployment_id, "pnl": round(realised + unrealised, 2),
            "realised": realised, "unrealised": unrealised, "open_positions": n_open, "ts": utcnow().isoformat()})


def ledger_pnl(trades: list[Any], ltp: dict[str, float]) -> tuple[float, float, int]:
    """Average-cost ledger over a deployment's fills -> (realised net of charges, unrealised, open positions)."""
    book: dict[tuple[str, str], list[float]] = {}
    realised = 0.0
    for t in trades:
        q, avg = book.get((t.symbol, t.product), [0.0, 0.0])
        signed = t.quantity if t.side == "BUY" else -t.quantity
        realised -= t.charges
        if q == 0 or (q > 0) == (signed > 0):
            avg = (avg * abs(q) + t.price * abs(signed)) / (abs(q) + abs(signed))
            q += signed
        else:
            closing = min(abs(q), abs(signed))
            realised += (t.price - avg) * closing * (1 if q > 0 else -1)
            q += signed
            if q and (q > 0) == (signed > 0):
                avg = t.price
            elif q == 0:
                avg = 0.0
        book[(t.symbol, t.product)] = [q, avg]
    unreal = sum((ltp.get(sym, avg) - avg) * q for (sym, _), (q, avg) in book.items() if q)
    return round(realised, 2), round(unreal, 2), sum(1 for (q, _) in book.values() if q)
