# Technical Indicators and Chart Patterns

## Moving averages

The **simple moving average (SMA)** averages the last N closes equally. The **exponential moving average (EMA)** weights recent prices more, reacting faster. Crossovers of a fast and a slow average (for example EMA 9 crossing above EMA 21) are classic trend-following entries; they work in trending markets and whipsaw in ranges. The 50-day and 200-day SMAs are widely watched: a 50-day crossing above the 200-day is called a golden cross, the reverse a death cross.

## RSI

The **Relative Strength Index** (Wilder, 14 periods by default) oscillates between 0 and 100. Readings above 70 are conventionally overbought and below 30 oversold. In strong trends RSI can stay overbought or oversold for long periods, so mean-reversion entries on RSI work best with a trend filter (for example only buying oversold dips while price is above the 200-day SMA). Bullish divergence occurs when price makes a lower low but RSI makes a higher low.

## MACD

**MACD** is the 12-period EMA minus the 26-period EMA; the **signal line** is a 9-period EMA of MACD, and the **histogram** is their difference. MACD crossing above its signal line is a momentum buy signal; crossing above zero confirms an uptrend.

## Bollinger Bands

**Bollinger Bands** plot a 20-period SMA with bands two standard deviations above and below. Band width measures volatility: a squeeze (narrow bands) often precedes a breakout. %B shows where price sits within the bands. Touching a band is not by itself a reversal signal.

## Supertrend

**Supertrend** (commonly period 10, multiplier 3) is an ATR-based trailing line. Price above the line means an uptrend (the direction output is +1), below means a downtrend (−1). It is popular for intraday index trading and as a trailing stop.

## ADX

The **Average Directional Index** measures trend strength regardless of direction. ADX above about 25 indicates a trending market; below 20 a range. Combining ADX with a directional signal (Supertrend, moving averages) filters out choppy periods.

## VWAP

**VWAP** is the session's volume-weighted average price. Intraday traders treat price above VWAP as bullish control and below as bearish; institutions benchmark execution against it. It resets every session and is not meaningful on daily bars.

## ATR

**Average True Range** measures average bar range including gaps. It is used for volatility-adjusted stop-losses (for example 1.5–3 × ATR) and position sizing.

## Stochastic, CCI and others

The **stochastic oscillator** compares the close to the recent high-low range (%K and %D lines). **CCI** measures deviation from a statistical mean. **Donchian channels** plot the highest high and lowest low over N periods and underpin breakout systems such as the Turtle rules. **Pivots** and **CPR** derive support and resistance from the previous session.

## Candlestick patterns

- **Doji** — open and close nearly equal; indecision.
- **Hammer / hanging man** — small body with a long lower shadow; potential reversal after a decline (hammer) or rally (hanging man).
- **Bullish / bearish engulfing** — a candle whose body engulfs the previous body in the opposite direction.
- **Morning star / evening star** — three-candle reversal patterns.
- **Three white soldiers / three black crows** — three strong consecutive candles in one direction.
- **Inside bar** — a bar within the previous bar's range; a breakout of the mother bar's range is often traded.
Patterns are more reliable at key support or resistance levels and with volume confirmation. AlgoDesk detects these patterns on the Technical dashboard and allows them as strategy conditions.

## Support and resistance

Support and resistance are price zones where buying or selling previously emerged. AlgoDesk clusters swing highs and lows and ranks levels by the number of touches. Levels with more touches and recent tests are stronger. Breakouts above resistance with rising volume are more credible than breakouts on low volume.

## Multi-timeframe analysis

Confirming a signal on a higher timeframe (for example taking 15-minute long entries only when the daily trend is up) reduces false signals. The Technical dashboard summarises trend, RSI, ADX and Supertrend on 15-minute, hourly and daily charts.
