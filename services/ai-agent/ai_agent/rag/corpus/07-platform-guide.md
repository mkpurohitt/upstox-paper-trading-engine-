# AlgoDesk Platform Guide

## What AlgoDesk does

AlgoDesk is an AI-first research and algorithmic trading platform for Indian markets. You can research with the Copilot and analysis dashboards, build strategies visually or as JSON, backtest them with Indian costs, paper-trade them on live prices, and deploy them to a connected broker with pre-trade risk checks. Paper trading is the default; live trading requires a connected broker and two-factor authentication.

## Copilot

The Copilot on the home page answers questions with live tools: quotes, candles, option chains, Greeks and payoffs, fundamentals, news, NSE data (FII/DII flows, corporate actions, results calendar, bulk and block deals, shareholding), screeners, scanners, your portfolio, and strategy generation and backtesting. Answers show rich cards and cite knowledge-base sources as [1], [2]. Use "Send to Builder" on a strategy card to open it in the Builder. The Copilot never places orders: it can only prepare a deployment, which you must confirm. Chats are saved in the history sidebar, where you can pin, rename, share (read-only link) or delete them. The Copilot provides education and data, not investment advice.

## Strategy DSL

Strategies are JSON documents with these main fields:

- `name`, `description`, `kind` — `equity`, `options` or `pair`.
- `universe` — `symbols` (e.g. `NSE:RELIANCE`) for equity strategies, `underlying` (e.g. `NIFTY`) for options, and `pair.leg_a`/`pair.leg_b` for pair trades.
- `timeframe` — one of 1m, 3m, 5m, 15m, 30m, 1h, 1d. `product` — MIS (intraday), CNC (delivery) or NRML (carry-forward F&O).
- `indicators` — a list of `{id, kind, params, source}` such as `{"id": "ema_fast", "kind": "EMA", "params": {"period": 9}}`. Supported kinds include SMA, EMA, WMA, VWAP, RSI, MACD, BBANDS, SUPERTREND, ATR, ADX, STOCH, CCI, OBV, ICHIMOKU, PIVOTS, CPR, HEIKIN_ASHI, ROC, DONCHIAN, HIGHEST, LOWEST, VOLUME_SMA, ZSCORE and HV. Multi-output indicators are referenced with a dot, e.g. `macd.signal` or `st.direction`.
- `entry` and `exit` — condition groups for `long` and `short`. A group is `{"kind": "all" | "any", "conditions": [...]}`. Conditions can be `compare` (left operand, operator, right operand), `time` windows, `day_of_week` or candlestick `pattern`. Operators are `>`, `<`, `>=`, `<=`, `==`, `crosses_above` and `crosses_below`. Operands are indicators (with an optional bar offset), price fields (open, high, low, close, volume, hl2, hlc3, ohlc4) or constants.
- `exit.stop_loss`, `exit.target` and `exit.trailing_sl` — percent, points or ATR multiples.
- `legs` (options) — each leg has an action (BUY/SELL), option type (CE/PE/FUT), a strike selector (`ATM_OFFSET` with an offset in strikes, `DELTA` with a target delta, or `PREMIUM` closest to a rupee value), an expiry (`current`, `next`, `monthly`), lots, and optional leg stop-loss/target percentages. `options_exit` adds combined stop-loss/target and an expiry-day exit time.
- `sizing` — `fixed_qty`, `fixed_lots`, `capital_pct` or `fixed_capital`.
- `schedule` — entry window (`entry_after`, `entry_before`), `square_off` time and trading days. `reentry` and `risk` (max loss per day, max trades per day, portfolio max loss) complete the definition.

## Builder

The Build page has three editors that stay in sync: a visual node graph, a form, and a Monaco JSON editor with schema validation. Templates include an EMA 9/21 crossover, a NIFTY short straddle with stop-loss, a Bank Nifty iron condor, an HDFCBANK/ICICIBANK pair trade, RSI mean reversion, a Supertrend + ADX trend rider and an opening range breakout. Every save creates a new version.

## Backtesting

Backtests run in a background worker and stream progress. Modes: event-driven (bar by bar, with intraday square-off, stops and options legs) and vectorised (fast, for simple equity rules). Results include equity and drawdown curves, monthly returns, trade list, day-of-week statistics, charges breakdown and metrics (CAGR, Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor, expectancy). Optimisation (grid or random search) and walk-forward analysis warn about overfitting; Monte Carlo simulation shows the spread of possible drawdowns. Options backtests price legs from historical option data when available and from a Black-Scholes model calibrated to volatility otherwise (flagged in the results).

## Deploying

From a saved strategy choose a mode: **Paper** (simulated fills on live prices, no money at risk), **Live** (real orders through your connected broker; needs 2FA and a fresh code to confirm) or **Notify only** (signals sent as alerts). Set capital, a multiplier, and risk limits (max loss per day, orders per minute, position value, lots per order). The Live page shows running deployments, logs, orders and P&L, with pause, resume, square-off and stop controls. All orders pass the risk engine and are tagged with the strategy and algo identifiers.

## Analysis dashboards

Twelve dashboards: Market Overview, Option Chain, Arbitrage Scanner, Ratio Spreads, Straddle/Strangle, Butterfly & Condor, Options Strategy Builder, Technical, Fundamental, Quant, Pairs and Screener. Each has filters, CSV export and an "Ask AI about this" button that sends the dashboard context to the Copilot. Saved screens can alert you when new stocks match.

## Safety features

- A kill switch in the top bar stops all deployments, cancels orders and squares off positions.
- Broker credentials are encrypted and never shown again after saving.
- The audit log records every order, deployment and administrative action in a tamper-evident hash chain.
- Two-factor authentication (TOTP) is required for live trading.
- You can export your data or delete your account from Profile (DPDP Act rights).
