# Options Basics: Pricing, Greeks and Volatility

## Calls and puts

A **call** gives the buyer the right, but not the obligation, to buy the underlying at the strike price on expiry; a **put** gives the right to sell. Indian index options are European-style (exercisable only at expiry) and cash-settled. Stock options are European-style and physically settled if held to expiry.

The option **premium** is intrinsic value plus time value. Intrinsic value of a call is max(0, spot − strike); of a put, max(0, strike − spot). Time value decays to zero at expiry.

Buyers risk only the premium paid, but most out-of-the-money options expire worthless. Sellers (writers) collect premium and take on potentially large losses, so exchanges require SPAN plus exposure margin from sellers.

## Black-Scholes and put-call parity

Option platforms, including AlgoDesk, use the Black-Scholes model to compute theoretical values, implied volatility and Greeks. Inputs are spot (or the futures price for index options), strike, time to expiry, risk-free rate (around 6.5% in India) and volatility.

**Put-call parity** links European calls and puts with the same strike and expiry: C − P = S − K·e^(−rT) (using the forward instead of spot when dividends or carry matter). A large deviation suggests a mispricing or, more often, stale quotes, wide bid-ask spreads or dividend effects. AlgoDesk's arbitrage scanner reports parity deviations net of an assumed cost.

## The Greeks

**Delta** measures how much the option price changes for a ₹1 move in the underlying. Calls have delta between 0 and 1, puts between −1 and 0. An ATM option has delta near ±0.5. Delta also approximates the probability that the option expires in the money. Position delta tells you your directional exposure in units of the underlying.

**Gamma** is the rate of change of delta. It is highest for ATM options close to expiry, which is why short ATM positions on expiry day can swing violently.

**Theta** is time decay: the change in option value per day, other things equal. Long options have negative theta; short options earn theta. Decay accelerates in the final days before expiry, especially for ATM strikes.

**Vega** is sensitivity to a one-point change in implied volatility. Long options are long vega and benefit from rising IV; short straddles and strangles are short vega and suffer when IV spikes (for example around events such as elections, budgets or RBI policy).

**Rho** is sensitivity to interest rates and is usually small for short-dated Indian options.

## Implied volatility

Implied volatility is forward-looking: it is the market's price of uncertainty. Typical NIFTY ATM IV ranges between about 10% and 20% in calm periods and spikes above 25–30% in stress. **IV skew** describes how IV differs across strikes; Indian index options usually show higher IV for OTM puts (crash protection) than for OTM calls.

**Expected move.** An approximate one-standard-deviation move to expiry is spot × IV × √(days/365). The price of the ATM straddle is another quick estimate of the expected move: roughly 0.8 × straddle price ≈ one standard deviation.

**IV vs realised volatility.** When IV is well above realised (historical) volatility, option sellers are being paid a premium; when IV is below realised volatility, options are relatively cheap. The IV/HV ratio on AlgoDesk's straddle dashboard tracks this.

## Expiry-day behaviour

On expiry day, theta and gamma are extreme. Premiums of OTM options collapse toward zero, while ATM premiums can still swing several-fold with small index moves. Many traders avoid carrying naked short positions into the final hour. Exchanges also apply additional extreme-loss margin on short options on expiry day.

## Margin

Option buyers pay the premium upfront. Sellers must post SPAN plus exposure margin, which for an index short straddle can be a large multiple of the premium received. Hedged structures (spreads, iron condors) receive margin benefits because their maximum loss is capped. Place hedge legs before short legs to obtain the margin benefit.
