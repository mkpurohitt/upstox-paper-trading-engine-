# Strategy DSL reference (v1.0)

Every strategy, however it was built (visual graph, form, JSON editor, code mode or the copilot), is stored and executed as one
declarative JSON document validated by `strategy_engine.dsl.StrategyDSL`. The backtester and the live runner execute the same
document, so a deployment behaves like its backtest. The JSON Schema is available at `GET /api/strategies/dsl/schema`; the
Monaco editor in the Builder validates against it as you type.

## Top-level fields

| Field | Type | Notes |
|---|---|---|
| `dsl_version` | `"1.0"` | |
| `name`, `description` | string | |
| `kind` | `equity` \| `options` \| `pair` | |
| `universe` | `{symbols: [...]}` or `{underlying: "NIFTY"}` | Equity: canonical symbols (`NSE:RELIANCE`). Options: underlying name. |
| `timeframe` | `1m` `3m` `5m` `15m` `30m` `1h` `1d` | Bar size the rules are evaluated on. |
| `product` | `MIS` \| `CNC` \| `NRML` | Intraday, delivery, carry-forward F&O. |
| `indicators` | `[{id, kind, params, source?, code?}]` | Up to 30. `id` is how conditions refer to it. |
| `entry` / `exit` | `{long?: Group, short?: Group}` | `exit` also takes `stop_loss`, `target`, `trailing_sl`, `max_holding_bars`. |
| `legs` | `[OptionLeg]` | Options only. |
| `options_exit` | `{combined_stop_loss_pct?, combined_target_pct?, stop_loss_amount?, target_amount?, exit_on_expiry_day_at?}` | Options only. |
| `pair` | `{leg_a, leg_b, lookback, entry_z, exit_z, stop_z, hedge: ols\|fixed, fixed_ratio?}` | Pair only. |
| `sizing` | `{mode: capital_pct\|fixed_qty\|fixed_lots\|fixed_capital, value}` | |
| `schedule` | `{entry_after, entry_before, square_off, days: [MON..FRI]}` | `HH:MM` IST; `square_off: null` to hold overnight. |
| `reentry` | `{enabled, max_per_day, cooldown_bars}` | |
| `risk` | `{max_loss_per_day?, max_trades_per_day?, portfolio_max_loss?, max_profit_per_day?}` | Strategy-level, on top of the account risk limits. |
| `tags` | string[] | |

## Conditions

A **group** is `{"kind": "all" | "any", "conditions": [...]}`; groups can nest. Condition kinds:

| kind | Shape | Example |
|---|---|---|
| `compare` | `{left: Operand, op, right: Operand}` | EMA 9 crosses above EMA 21 |
| `time` | `{after?: "HH:MM", before?: "HH:MM"}` | only between 09:30 and 11:30 |
| `day_of_week` | `{days: ["MON", ...]}` | Mondays to Wednesdays |
| `pattern` | `{name, lookback?}` | `bullish_engulfing`, `morning_star`, `breakout_high`, … (`lookback` bars, default 20, for breakout patterns) |

Operators: `>` `<` `>=` `<=` `==` `crosses_above` `crosses_below`.

Operands:

```jsonc
{"type": "indicator", "ref": "ema_fast", "offset": 0}   // offset 1 = previous bar; multi-output: "macd.signal", "st.direction"
{"type": "price", "field": "close"}                      // open high low close volume hl2 hlc3 ohlc4
{"type": "const", "value": 30}
```

Patterns: `doji`, `hammer`, `inverted_hammer`, `shooting_star`, `bullish_engulfing`, `bearish_engulfing`, `morning_star`,
`evening_star`, `inside_bar`, `outside_bar`, `three_white_soldiers`, `three_black_crows`, `breakout_high`, `breakdown_low`, `gap_up`,
`gap_down`.

## Exits and stops

```jsonc
"exit": {
  "long":  {"kind": "any", "conditions": [ ... ]},
  "stop_loss":   {"type": "percent", "value": 1.0},              // percent | points | atr (with atr_period)
  "target":      {"type": "percent", "value": 2.0},
  "trailing_sl": {"type": "percent", "value": 0.6, "activate_after": 0.5},
  "max_holding_bars": 20
}
```

When the stop and the target are both touched within one bar, the backtester assumes the stop filled first (conservative). Gaps fill
at the open.

## Indicators

| kind | Parameters (defaults) | Outputs | Pane |
|---|---|---|---|
| `SMA` | period=20 | value | overlay |
| `EMA` | period=20 | value | overlay |
| `WMA` | period=20 | value | overlay |
| `VWAP` | — | value | overlay |
| `RSI` | period=14 | value | oscillator |
| `MACD` | fast=12, slow=26, signal=9 | macd, signal, hist | oscillator |
| `BBANDS` | period=20, std=2.0 | upper, middle, lower, width, pct_b | overlay |
| `SUPERTREND` | period=10, multiplier=3.0 | value, direction | overlay |
| `ATR` | period=14 | value | oscillator |
| `ADX` | period=14 | adx, plus_di, minus_di | oscillator |
| `STOCH` | k=14, d=3, smooth=3 | k, d | oscillator |
| `CCI` | period=20 | value | oscillator |
| `OBV` | — | value | oscillator |
| `ICHIMOKU` | tenkan=9, kijun=26, senkou=52 | tenkan, kijun, senkou_a, senkou_b, chikou | overlay |
| `PIVOTS` | — | pp, r1, s1, r2, s2, r3, s3 | overlay |
| `CPR` | — | pivot, tc, bc, width_pct | overlay |
| `HEIKIN_ASHI` | — | open, high, low, close | overlay |
| `ROC` | period=10 | value | oscillator |
| `DONCHIAN` | period=20 | upper, lower, middle | overlay |
| `HIGHEST` / `LOWEST` | period=20 | value | overlay |
| `VOLUME_SMA` | period=20 | value | oscillator |
| `ZSCORE` | period=20 | value | oscillator |
| `HV` | period=20 | value | oscillator |
| `CUSTOM` | your params | value | — |

`source` selects the input series (`close` by default; e.g. `high` for `HIGHEST`). `CUSTOM` takes `code` with
`def compute(df, params): ...` returning a Series aligned to `df`. It runs in the sandbox described in ARCHITECTURE.md (no imports,
no I/O, CPU and memory limits).

## Options legs

```jsonc
{
  "id": "short_ce",
  "action": "SELL",                       // BUY | SELL
  "option_type": "CE",                    // CE | PE | FUT
  "strike": {"mode": "ATM_OFFSET", "offset": 0},   // or {"mode": "DELTA", "delta": 0.2} or {"mode": "PREMIUM", "premium": 50}
  "expiry": "current",                    // current | next | monthly
  "lots": 1,
  "stop_loss_pct": 30,                    // optional leg SL, % of entry premium
  "target_pct": 50
}
```

Strikes are resolved on the live chain at entry time (ATM from the spot/forward; the delta target uses Black-Scholes on chain IV).
Options backtests price legs with Black-Scholes on the modelled IV surface (mock data) or realised volatility plus skew (live underlying
data), which the results flag.

## Examples

### EMA crossover (equity, intraday)

```json
{
  "dsl_version": "1.0", "name": "EMA 9/21 crossover", "kind": "equity",
  "universe": {"symbols": ["NSE:RELIANCE", "NSE:HDFCBANK"]}, "timeframe": "15m", "product": "MIS",
  "indicators": [{"id": "ema_fast", "kind": "EMA", "params": {"period": 9}},
                 {"id": "ema_slow", "kind": "EMA", "params": {"period": 21}}],
  "entry": {"long": {"kind": "all", "conditions": [{"kind": "compare", "left": {"type": "indicator", "ref": "ema_fast"},
                                                    "op": "crosses_above", "right": {"type": "indicator", "ref": "ema_slow"}}]}},
  "exit": {"long": {"kind": "any", "conditions": [{"kind": "compare", "left": {"type": "indicator", "ref": "ema_fast"},
                                                   "op": "crosses_below", "right": {"type": "indicator", "ref": "ema_slow"}}]},
           "stop_loss": {"type": "percent", "value": 0.8}, "target": {"type": "percent", "value": 1.6}},
  "sizing": {"mode": "capital_pct", "value": 25},
  "schedule": {"entry_after": "09:30", "entry_before": "14:30", "square_off": "15:15"},
  "risk": {"max_loss_per_day": 15000, "max_trades_per_day": 6}
}
```

### NIFTY short straddle with leg stop-loss (options)

```json
{
  "dsl_version": "1.0", "name": "NIFTY short straddle with SL", "kind": "options",
  "universe": {"underlying": "NIFTY"}, "timeframe": "5m", "product": "MIS",
  "legs": [
    {"id": "ce", "action": "SELL", "option_type": "CE", "strike": {"mode": "ATM_OFFSET", "offset": 0}, "expiry": "current", "lots": 1, "stop_loss_pct": 30},
    {"id": "pe", "action": "SELL", "option_type": "PE", "strike": {"mode": "ATM_OFFSET", "offset": 0}, "expiry": "current", "lots": 1, "stop_loss_pct": 30}
  ],
  "options_exit": {"combined_target_pct": 50, "stop_loss_amount": 6000},
  "sizing": {"mode": "fixed_lots", "value": 1},
  "schedule": {"entry_after": "09:20", "entry_before": "10:00", "square_off": "15:15"}
}
```

### HDFCBANK / ICICIBANK pair trade

```json
{
  "dsl_version": "1.0", "name": "HDFCBANK / ICICIBANK pair trade", "kind": "pair",
  "universe": {"symbols": ["NSE:HDFCBANK", "NSE:ICICIBANK"]}, "timeframe": "1d", "product": "NRML",
  "pair": {"leg_a": "NSE:HDFCBANK", "leg_b": "NSE:ICICIBANK", "lookback": 60, "entry_z": 2.0, "exit_z": 0.5, "stop_z": 4.0, "hedge": "ols"},
  "sizing": {"mode": "fixed_capital", "value": 500000}
}
```

More templates (Bank Nifty iron condor, RSI mean reversion, Supertrend + ADX, opening range breakout) are available from
`GET /api/strategies/templates` and the Builder's template picker. The copilot can draft any of these from plain English.
