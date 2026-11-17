# Indian Trading Costs and Charges

## Components

Every trade in India carries several statutory and exchange charges on top of brokerage:

- **Securities Transaction Tax (STT)** — levied by the government on the value of securities transactions.
- **Exchange transaction charges** — levied by NSE, BSE or MCX on turnover.
- **SEBI turnover fees** — ₹10 per crore of turnover.
- **Stamp duty** — charged on the buy side only, at rates set under the Indian Stamp Act.
- **GST** — 18% on brokerage, exchange transaction charges and SEBI fees (not on STT or stamp duty).
- **Brokerage** — discount brokers typically charge zero for equity delivery and a flat ₹20 or 0.03% (whichever is lower) per executed order for intraday and F&O; full-service brokers charge a percentage.
- **DP charges** — a flat depository charge per scrip when delivery shares are sold.

## STT rates (from 1 October 2024)

| Segment | Rate |
|---|---|
| Equity delivery | 0.1% on buy and sell value |
| Equity intraday | 0.025% on sell value |
| Futures | 0.02% on sell value |
| Options (sold) | 0.1% on sell-side premium |
| Options exercised | 0.125% of intrinsic value |

The Finance (No.2) Act 2024 raised futures STT from 0.0125% to 0.02% and options STT from 0.0625% to 0.1% of premium with effect from 1 October 2024.

The Union Budget 2026 proposed a further increase in F&O STT (futures to 0.05% and options to 0.15% of premium) effective 1 April 2026. AlgoDesk's cost model applies this as a separate effective-dated regime that is flagged for verification against the enacted Finance Act; administrators can override any rate.

## Exchange transaction charges (NSE, uniform rates from 1 October 2024)

| Segment | Rate |
|---|---|
| Equity (cash) | 0.00297% of turnover |
| Equity futures | 0.00173% of turnover |
| Equity options | 0.03503% of premium turnover |

Before October 2024 NSE used slab-based charges with volume rebates; SEBI's directive moved exchanges to uniform true-to-label charges.

## Stamp duty (buy side)

| Segment | Rate |
|---|---|
| Equity delivery | 0.015% |
| Equity intraday | 0.003% |
| Futures | 0.002% |
| Options | 0.003% of premium |

## Worked example: NIFTY options round trip

Buying and selling one lot of NIFTY options at a premium of ₹100 with a lot size of 65 gives premium turnover of ₹6,500 on each side. STT applies only on the sell side (0.1% of ₹6,500 = ₹6.50). Exchange charges at 0.03503% are about ₹2.28 per side. Brokerage of ₹20 per order, GST at 18% on brokerage plus exchange and SEBI fees, and stamp duty of 0.003% on the buy side bring the total round trip to roughly ₹55–60, i.e. close to 1 point of NIFTY premium per lot. For strategies that capture a few points per trade, costs are a large fraction of gross profit.

## Taxes on profits

Profits from intraday equity trading are taxed as speculative business income. F&O profits are non-speculative business income, taxed at slab rates, and may require a tax audit above certain turnover thresholds. Long-term capital gains on listed equity held over 12 months are taxed at 12.5% above an annual exemption (₹1.25 lakh from July 2024), and short-term gains at 20%. Consult a tax professional; this is general information only.

## How AlgoDesk models costs

The backtester and the paper broker compute charges per fill using the effective-dated regime for the trade date, the segment (equity delivery, intraday, futures, options, commodity) and the selected broker's brokerage plan. Backtest reports show a charges breakdown (brokerage, STT, exchange, SEBI, stamp, GST) and charges as a percentage of gross P&L.
