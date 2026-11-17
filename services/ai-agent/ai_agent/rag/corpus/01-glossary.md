# Trading and Derivatives Glossary (India)

## Market structure

**NSE / BSE / MCX.** The National Stock Exchange and BSE list equities, equity derivatives (F&O) and currency derivatives. MCX is the main commodity derivatives exchange (crude oil, natural gas, gold, silver, base metals). NSE's equity derivatives segment is often called NFO in broker APIs and BSE's is BFO.

**Segments.** Cash (spot equity), F&O (index and stock futures and options), currency derivatives and commodity derivatives. Each segment has its own margin rules, charges and trading hours. NSE equity and F&O trade 09:15–15:30 IST with a pre-open session from 09:00 to 09:15. MCX trades until 23:30 (23:55 for some contracts during US daylight saving).

**Lot size.** Derivatives trade in fixed contract multiples called lots. Exchanges revise lot sizes periodically so that contract value stays within the band set by SEBI; always read the current lot size from the instrument master rather than hard-coding it.

**Freeze quantity.** The maximum quantity allowed in a single order for a derivative contract. Larger orders must be split ("sliced") into multiple orders, each at or below the freeze quantity. AlgoDesk slices automatically.

**Circuit limits / price bands.** Daily price bands on stocks (2%, 5%, 10% or 20%). Index-wide circuit breakers halt trading at 10%, 15% and 20% moves of the NIFTY 50 or Sensex. F&O stocks have dynamic price bands instead of fixed circuits.

**F&O ban period.** A stock enters the ban when open interest across all its futures and options exceeds 95% of the market-wide position limit (MWPL). During the ban, traders may only reduce existing positions; new positions are penalised.

## Order and product types

**CNC / delivery.** Cash-and-carry: shares bought are delivered to your demat account. No leverage.

**MIS / intraday.** Margin Intraday Square-off: positions must be closed the same day and brokers auto square-off near the close (typically 15:15–15:25 for equity). Intraday leverage on equity is capped by SEBI peak-margin rules (about 5x for most liquid stocks).

**NRML.** Normal product for carrying F&O (and commodity) positions overnight with full SPAN + exposure margin.

**Market, limit, SL and SL-M orders.** A market order executes at the best available price. A limit order executes at the specified price or better. A stop-loss (SL) order becomes a limit order once the trigger price is touched; SL-M becomes a market order at the trigger. Exchanges have discouraged SL-M for options because of slippage risk in illiquid strikes.

**GTT (good till triggered).** A broker-side conditional order valid for up to a year; it places a limit order when the trigger is hit.

## Derivatives terms

**Open interest (OI).** The number of outstanding derivative contracts that have not been closed or settled. Rising OI with rising price is read as long buildup; rising OI with falling price as short buildup; falling OI with rising price as short covering; falling OI with falling price as long unwinding.

**PCR (put-call ratio).** Total put open interest divided by total call open interest for an expiry. A PCR above about 1.0–1.2 means put writers dominate, which many traders read as support below the market; a low PCR (below about 0.7–0.8) means call writing dominates, often read as resistance. PCR is a sentiment gauge, not a timing signal, and extreme readings can be contrarian.

**Max pain.** The strike at which the total intrinsic value payable to option buyers at expiry would be smallest — i.e. where option writers as a group lose the least. Some traders expect the index to gravitate toward max pain near expiry; evidence is mixed, and max pain moves as OI changes.

**Implied volatility (IV).** The volatility input that makes the Black-Scholes price equal the market price of an option. High IV means expensive options. **India VIX** is NSE's 30-day implied volatility index for NIFTY options.

**Historical / realised volatility (HV).** The annualised standard deviation of past returns, e.g. 20-day HV. Comparing IV with HV shows whether options are rich or cheap relative to recent movement.

**Basis.** Futures price minus spot price. Positive basis (contango) reflects cost of carry: interest minus expected dividends. **Cash-and-carry arbitrage** buys spot and sells futures when the annualised basis exceeds financing and trading costs.

**Moneyness.** In-the-money (ITM) options have intrinsic value; at-the-money (ATM) strikes are closest to spot; out-of-the-money (OTM) options have only time value.

**Expiry.** NSE index options have a single weekly expiry (NIFTY) and monthly expiries for other indices; BSE has weekly Sensex options. Since September 2025 SEBI restricted expiry days to Tuesday or Thursday: NSE contracts expire on Tuesdays and BSE contracts on Thursdays (if that day is a holiday, the previous trading day). Stock options and futures expire monthly on the last Tuesday for NSE.

**Physical settlement.** Stock F&O contracts held to expiry are settled by delivery of shares, which needs the full contract value (or the shares). Index derivatives are cash-settled.

## Indicators and analytics

**VWAP.** Volume-weighted average price for the session; used as an intraday fair-value benchmark.

**ATR.** Average True Range, a volatility measure used to size stops (e.g. 2 × ATR).

**Supertrend.** A trailing band built from ATR around the median price; the direction flips when price closes beyond the band.

**CPR (central pivot range).** Pivot, bottom-central and top-central levels from the previous day's high, low and close; narrow CPR days often precede trending sessions.

**Max drawdown.** The largest peak-to-trough decline of an equity curve. **Sharpe ratio** is excess return per unit of volatility; **Sortino** penalises only downside volatility; **Calmar** is CAGR divided by max drawdown.
