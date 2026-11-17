# Options Strategies Handbook

## Short straddle

Sell an ATM call and an ATM put of the same expiry. Profit is maximal (the full premium) if the underlying expires exactly at the strike. Breakevens are strike ± total premium received. Risk is unlimited on both sides. It is a short-volatility, positive-theta, negative-gamma trade: it earns time decay when the market stays in a range and loses quickly on large moves or IV spikes. Common risk controls are a leg-wise stop-loss of 25–50% of the leg premium, a combined stop-loss in rupees, and exiting before major events. The popular intraday variant sells at 09:20 and squares off by 15:15.

## Short strangle

Sell an OTM call and an OTM put. It collects less premium than a straddle but has wider breakevens and a higher probability of profit. Risk remains unlimited, so position size and stop-losses matter more than the probability statistic.

## Long straddle and long strangle

Buy both a call and a put to profit from a large move in either direction or an IV increase. They are negative-theta trades that lose money if the market stays quiet; they are typically used ahead of events where the expected move may be underpriced.

## Iron condor

Sell an OTM call spread and an OTM put spread: short call and short put a few strikes away from ATM, plus long wings further out. Maximum profit is the net credit; maximum loss is the wing width minus the credit, multiplied by the lot size. Margin is much lower than an unhedged strangle because risk is defined. Iron condors work best in range-bound markets with elevated IV; they are hurt by trends and gap moves. A common rule is to take profit at 50–60% of the credit and to cut or adjust when a short strike is threatened (delta of the short leg above about 0.30–0.35).

## Iron butterfly (iron fly)

Sell an ATM straddle and buy OTM wings on both sides. It collects a larger credit than a condor and has a higher maximum profit, but a narrower profit zone and lower probability of profit. Maximum loss is the wing width minus the credit.

## Butterflies

A long call butterfly buys one lower-strike call, sells two ATM calls and buys one higher-strike call (equal wing widths). It is a low-cost debit trade that profits if the underlying finishes near the middle strike. Maximum loss is the debit paid. Broken-wing butterflies use unequal wings to reduce cost or remove risk on one side.

## Vertical spreads

A **bull call spread** buys a lower-strike call and sells a higher-strike call: a debit, limited-risk bullish trade. A **bear put spread** buys a higher-strike put and sells a lower-strike put. **Credit spreads** (bull put, bear call) sell the closer strike and buy protection further out; they profit from time decay if the short strike is not breached. Spreads cap both profit and loss and receive margin benefits.

## Ratio spreads

A 1×2 or 1×3 front ratio spread buys one option and sells two or three further-OTM options of the same type. They can often be put on for a credit or zero cost. Profit is maximal at the short strike at expiry; beyond the upper breakevens the extra short options create unlimited risk. Ratio spreads suit a moderately directional view with a belief that the move will be limited. Margin requirements are similar to naked short options.

## Calendar spreads

Sell a near-expiry option and buy a later-expiry option at the same strike. The trade profits from the faster decay of the near-month option and from a rise in back-month IV. It loses if the underlying moves far from the strike.

## Pair trading (statistical arbitrage)

Pair trading takes offsetting long and short positions in two historically related stocks (e.g. two private banks) when their spread diverges from its mean, betting on mean reversion. Robust practice tests for **cointegration** (Engle-Granger, Johansen), estimates a **hedge ratio** by regression, measures the **half-life** of mean reversion, and trades z-score thresholds (for example, enter at ±2, exit near 0, stop at ±3.5). Cointegration can break down after corporate events or regime changes, so re-test regularly. In India, short positions held overnight must use futures because short-selling shares in the cash market requires delivery by the end of the day.

## Choosing a structure

- Neutral view, high IV: iron condor, iron fly, short strangle (with stops).
- Neutral view, low IV: long butterfly, calendar spread.
- Directional view, low cost: vertical debit spread.
- Expecting a big move: long straddle or strangle.
- Always check liquidity (bid-ask spreads, OI) of every strike, total charges, margin and the worst-case loss before trading.
