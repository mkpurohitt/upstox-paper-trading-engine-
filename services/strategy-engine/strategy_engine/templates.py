"""Built-in strategy templates (also used as seed demo strategies)."""

from __future__ import annotations

from typing import Any


def _cmp(left: dict[str, Any], op: str, right: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "compare", "left": left, "op": op, "right": right}


def _ind(ref: str, offset: int = 0) -> dict[str, Any]:
    return {"type": "indicator", "ref": ref, "offset": offset}


def _px(field: str = "close") -> dict[str, Any]:
    return {"type": "price", "field": field}


def _k(v: float) -> dict[str, Any]:
    return {"type": "const", "value": v}


TEMPLATES: list[dict[str, Any]] = [
    {
        "dsl_version": "1.0", "name": "EMA 9/21 crossover", "kind": "equity",
        "description": "Trend-following intraday crossover on liquid large caps with fixed SL/target and trailing stop.",
        "universe": {"symbols": ["NSE:RELIANCE", "NSE:HDFCBANK", "NSE:INFY"]}, "timeframe": "15m", "product": "MIS",
        "indicators": [{"id": "ema_fast", "kind": "EMA", "params": {"period": 9}},
                       {"id": "ema_slow", "kind": "EMA", "params": {"period": 21}}],
        "entry": {"long": {"kind": "all", "conditions": [_cmp(_ind("ema_fast"), "crosses_above", _ind("ema_slow"))]},
                  "short": {"kind": "all", "conditions": [_cmp(_ind("ema_fast"), "crosses_below", _ind("ema_slow"))]}},
        "exit": {"long": {"kind": "any", "conditions": [_cmp(_ind("ema_fast"), "crosses_below", _ind("ema_slow"))]},
                 "short": {"kind": "any", "conditions": [_cmp(_ind("ema_fast"), "crosses_above", _ind("ema_slow"))]},
                 "stop_loss": {"type": "percent", "value": 0.8}, "target": {"type": "percent", "value": 1.6},
                 "trailing_sl": {"type": "percent", "value": 0.6, "activate_after": 0.5}},
        "sizing": {"mode": "capital_pct", "value": 25},
        "schedule": {"entry_after": "09:30", "entry_before": "14:30", "square_off": "15:15"},
        "risk": {"max_loss_per_day": 15000, "max_trades_per_day": 6}, "tags": ["trend", "intraday", "template"],
    },
    {
        "dsl_version": "1.0", "name": "NIFTY short straddle with SL", "kind": "options",
        "description": "Sell ATM CE + PE of the current weekly expiry at 09:20, 30% leg-wise SL, exit 15:15.",
        "universe": {"underlying": "NIFTY"}, "timeframe": "5m", "product": "MIS",
        "legs": [
            {"id": "ce", "action": "SELL", "option_type": "CE", "strike": {"mode": "ATM_OFFSET", "offset": 0},
             "expiry": "current", "lots": 1, "stop_loss_pct": 30},
            {"id": "pe", "action": "SELL", "option_type": "PE", "strike": {"mode": "ATM_OFFSET", "offset": 0},
             "expiry": "current", "lots": 1, "stop_loss_pct": 30},
        ],
        "options_exit": {"combined_target_pct": 50, "stop_loss_amount": 6000},
        "sizing": {"mode": "fixed_lots", "value": 1},
        "schedule": {"entry_after": "09:20", "entry_before": "10:00", "square_off": "15:15"},
        "reentry": {"enabled": False, "max_per_day": 0, "cooldown_bars": 0},
        "risk": {"max_loss_per_day": 8000}, "tags": ["options", "theta", "template"],
    },
    {
        "dsl_version": "1.0", "name": "Bank Nifty iron condor", "kind": "options",
        "description": "Sell ~0.20 delta CE/PE and buy wings 4 strikes further out on the monthly expiry; hold with combined SL.",
        "universe": {"underlying": "BANKNIFTY"}, "timeframe": "15m", "product": "NRML",
        "legs": [
            {"id": "short_ce", "action": "SELL", "option_type": "CE", "strike": {"mode": "DELTA", "delta": 0.2}, "expiry": "monthly", "lots": 1},
            {"id": "long_ce", "action": "BUY", "option_type": "CE", "strike": {"mode": "ATM_OFFSET", "offset": 12}, "expiry": "monthly", "lots": 1},
            {"id": "short_pe", "action": "SELL", "option_type": "PE", "strike": {"mode": "DELTA", "delta": 0.2}, "expiry": "monthly", "lots": 1},
            {"id": "long_pe", "action": "BUY", "option_type": "PE", "strike": {"mode": "ATM_OFFSET", "offset": -12}, "expiry": "monthly", "lots": 1},
        ],
        "options_exit": {"combined_stop_loss_pct": 100, "combined_target_pct": 60, "exit_on_expiry_day_at": "14:30"},
        "sizing": {"mode": "fixed_lots", "value": 1},
        "schedule": {"entry_after": "09:45", "entry_before": "11:00", "square_off": None, "days": ["MON", "TUE", "WED"]},
        "tags": ["options", "range", "template"],
    },
    {
        "dsl_version": "1.0", "name": "HDFCBANK / ICICIBANK pair trade", "kind": "pair",
        "description": "Mean-reversion on the log-price spread with a rolling OLS hedge ratio; enter at |z|>2, exit at |z|<0.5.",
        "universe": {"symbols": ["NSE:HDFCBANK", "NSE:ICICIBANK"]}, "timeframe": "1d", "product": "CNC",
        "pair": {"leg_a": "NSE:HDFCBANK", "leg_b": "NSE:ICICIBANK", "lookback": 60, "entry_z": 2.0, "exit_z": 0.5, "stop_z": 4.0},
        "exit": {"max_holding_bars": 30}, "sizing": {"mode": "capital_pct", "value": 40},
        "schedule": {"entry_after": None, "entry_before": None, "square_off": None}, "tags": ["stat-arb", "template"],
    },
    {
        "dsl_version": "1.0", "name": "RSI mean reversion (daily)", "kind": "equity",
        "description": "Buy oversold dips above the 200-DMA, exit on RSI recovery. Positional (CNC).",
        "universe": {"symbols": ["NSE:TCS", "NSE:ITC", "NSE:SBIN", "NSE:LT"]}, "timeframe": "1d", "product": "CNC",
        "indicators": [{"id": "rsi", "kind": "RSI", "params": {"period": 14}},
                       {"id": "sma200", "kind": "SMA", "params": {"period": 200}}],
        "entry": {"long": {"kind": "all", "conditions": [_cmp(_ind("rsi"), "<", _k(30)), _cmp(_px(), ">", _ind("sma200"))]}},
        "exit": {"long": {"kind": "any", "conditions": [_cmp(_ind("rsi"), ">", _k(60))]},
                 "stop_loss": {"type": "percent", "value": 6}, "max_holding_bars": 20},
        "sizing": {"mode": "capital_pct", "value": 20},
        "schedule": {"entry_after": None, "entry_before": None, "square_off": None}, "tags": ["mean-reversion", "template"],
    },
    {
        "dsl_version": "1.0", "name": "Supertrend + ADX trend rider", "kind": "equity",
        "description": "Ride Supertrend flips when ADX confirms a trend. ATR-based stop.",
        "universe": {"symbols": ["NSE:TATASTEEL", "NSE:BAJFINANCE"]}, "timeframe": "1h", "product": "NRML",
        "indicators": [{"id": "st", "kind": "SUPERTREND", "params": {"period": 10, "multiplier": 3}},
                       {"id": "adx", "kind": "ADX", "params": {"period": 14}}],
        "entry": {"long": {"kind": "all", "conditions": [_cmp(_ind("st.direction"), ">", _k(0)), _cmp(_ind("st.direction", 1), "<", _k(0)), _cmp(_ind("adx.adx"), ">", _k(20))]},
                  "short": {"kind": "all", "conditions": [_cmp(_ind("st.direction"), "<", _k(0)), _cmp(_ind("st.direction", 1), ">", _k(0)), _cmp(_ind("adx.adx"), ">", _k(20))]}},
        "exit": {"long": {"kind": "any", "conditions": [_cmp(_ind("st.direction"), "<", _k(0))]},
                 "short": {"kind": "any", "conditions": [_cmp(_ind("st.direction"), ">", _k(0))]},
                 "stop_loss": {"type": "atr", "value": 2, "atr_period": 14}},
        "sizing": {"mode": "capital_pct", "value": 30},
        "schedule": {"entry_after": None, "entry_before": None, "square_off": None}, "tags": ["trend", "template"],
    },
    {
        "dsl_version": "1.0", "name": "Opening range breakout (15m)", "kind": "equity",
        "description": "Enter on a breakout of the first 15-minute range, confirmed by VWAP; square off 15:10.",
        "universe": {"symbols": ["NSE:SBIN", "NSE:AXISBANK"]}, "timeframe": "5m", "product": "MIS",
        "indicators": [{"id": "hh", "kind": "HIGHEST", "params": {"period": 3}, "source": "high"},
                       {"id": "ll", "kind": "LOWEST", "params": {"period": 3}, "source": "low"},
                       {"id": "vwap", "kind": "VWAP", "params": {}, "source": "hlc3"}],
        "entry": {"long": {"kind": "all", "conditions": [_cmp(_px(), ">", _ind("hh", 1)), _cmp(_px(), ">", _ind("vwap")),
                                                          {"kind": "time", "after": "09:30", "before": "11:30"}]},
                  "short": {"kind": "all", "conditions": [_cmp(_px(), "<", _ind("ll", 1)), _cmp(_px(), "<", _ind("vwap")),
                                                           {"kind": "time", "after": "09:30", "before": "11:30"}]}},
        "exit": {"stop_loss": {"type": "percent", "value": 0.7}, "target": {"type": "percent", "value": 1.4}},
        "sizing": {"mode": "capital_pct", "value": 25},
        "schedule": {"entry_after": "09:30", "entry_before": "11:30", "square_off": "15:10"},
        "risk": {"max_trades_per_day": 2}, "tags": ["breakout", "intraday", "template"],
    },
]


def template_by_name(name: str) -> dict[str, Any] | None:
    return next((t for t in TEMPLATES if t["name"] == name), None)
