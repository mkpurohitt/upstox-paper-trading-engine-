# Risk Management and Robust Backtesting

## Position sizing

Size positions from risk, not conviction. A common rule risks a fixed fraction of capital per trade (for example 0.5–1%): quantity = (capital × risk%) ÷ (entry − stop). For options, size by maximum loss of the structure, and remember that unlimited-risk structures need a hard stop and a gap-risk allowance. The Kelly criterion gives a theoretical optimum fraction but is very sensitive to estimation error; practitioners use a quarter or half of Kelly at most.

## Stop-losses and exits

- **Fixed percentage** stops are simple but ignore volatility.
- **ATR-based** stops (for example 2 × ATR) adapt to volatility.
- **Trailing stops** lock in gains as the trade moves in your favour.
- **Time stops** exit trades that do not work within a set number of bars.
- **Combined stops** for multi-leg options cap the MTM loss of the whole structure.
Exits that reduce risk should never be blocked by platform limits: AlgoDesk always allows reducing orders, even when a daily loss limit has been breached.

## Daily and portfolio limits

Set a maximum loss per day, a maximum number of trades or orders per minute, a cap on position value and on lots per order. Diversify across uncorrelated strategies and instruments; many "different" strategies on Indian indices are highly correlated in a sell-off. Track gross and net exposure, concentration (the share of capital in the largest position) and the Herfindahl-Hirschman Index of weights.

## Kill switch

A kill switch immediately stops all strategies, cancels open orders and squares off positions. Use it when something behaves unexpectedly: duplicate orders, a data feed freeze, or losses beyond plan. AlgoDesk provides a user kill switch in the top bar and an administrator platform-wide kill switch.

## Overfitting and data snooping

A backtest that has been tuned on the same data it is evaluated on will overstate performance. Warning signs:

- Many parameters relative to the number of trades (fewer than about 30–50 trades is statistically weak).
- Performance that collapses with small parameter changes (no "plateau").
- Sharpe ratios above about 3 on daily data, or very high win rates with rare large losses.
- Results that depend on a few outlier trades.
- Look-ahead bias (using information not available at the time) and survivorship bias (testing only today's index constituents).

## Walk-forward analysis

Walk-forward optimisation splits history into rolling windows: optimise parameters on the in-sample part, test them on the following out-of-sample part, then roll forward. The stitched out-of-sample equity curve is a more honest estimate of live performance. Compare in-sample and out-of-sample Sharpe: a large drop signals overfitting. AlgoDesk reports walk-forward efficiency and warns when it is low.

## Monte Carlo simulation

Monte Carlo reshuffles or resamples the sequence of trade returns thousands of times to estimate the distribution of drawdowns and final equity. Plan capital around the 95th-percentile drawdown, not the single historical path. It also shows the probability of ruin for a given risk per trade.

## Costs and slippage

Indian transaction costs (STT, exchange charges, GST, stamp duty, SEBI fees and brokerage) are a large drag for high-frequency intraday and options strategies. Options STT is charged on the sell-side premium, and exchange transaction charges on options are levied on premium turnover, so strategies that trade cheap premiums frequently can see costs consume most of the gross edge. Always backtest with realistic slippage (a few basis points for liquid large caps and index futures, more for illiquid strikes) and compare net P&L with the charges paid.

## Paper trading before live

Run a strategy in paper mode on live prices for at least a few weeks before risking capital. Compare paper fills with backtest assumptions; differences reveal slippage and execution issues. Then start live with minimal size and scale up gradually.

## Behavioural risk

Common failure modes are increasing size after losses, removing stop-losses, and overriding a system after a drawdown. Decide rules in advance, automate them, and review performance on a schedule rather than trade by trade.
