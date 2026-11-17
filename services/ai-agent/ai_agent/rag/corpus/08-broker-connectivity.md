# Broker Connectivity Notes

## Supported brokers

AlgoDesk connects to Upstox, Zerodha (Kite Connect), Angel One (SmartAPI), Dhan, Fyers, Kotak Neo, 5paisa, ICICI Direct (Breeze), Alice Blue and Shoonya (Finvasia), plus a built-in paper broker that is the default for every user.

## Authentication patterns

- **OAuth / request-token login (Upstox, Zerodha, Fyers, Dhan, ICICI Breeze, Alice Blue).** You register an app with the broker, enter its API key and secret in AlgoDesk, and complete a browser login. The broker returns a short-lived request token that AlgoDesk exchanges for an access token. Access tokens are valid for one trading day and typically expire early the next morning (around 06:00 IST for Kite and Upstox), so a fresh login is needed each day.
- **TOTP-based login (Angel One, Kotak Neo, Shoonya, 5paisa).** These APIs accept the client code, a PIN or password and a time-based one-time password generated from a TOTP secret. If you store the TOTP secret, AlgoDesk can renew the session automatically; it is encrypted at rest with a key bound to your account.
- **Checksums.** Some APIs (for example ICICI Breeze) require a checksum header computed from a timestamp, the request body and your secret.

## Static IP and API keys

Under SEBI's retail algo framework, brokers issue API keys bound to a client (and vendor) and require orders to originate from a whitelisted static IP. Register AlgoDesk's egress IP (shown on the broker connection screen and configured by the administrator as EGRESS_STATIC_IP) in your broker's developer console. Orders from other IPs may be rejected.

## Rate limits

Brokers enforce their own API rate limits (commonly around 10 orders per second and a few hundred to a few thousand orders per day, varying by broker and endpoint) in addition to the exchange order-per-second threshold for unregistered algos. AlgoDesk throttles orders per second per client per exchange and per minute per user and strategy, and slices orders above the exchange freeze quantity.

## Product and order type mapping

AlgoDesk uses canonical products — CNC, MIS, NRML — and order types — MARKET, LIMIT, SL, SL-M — and maps them to each broker's vocabulary (for example Upstox uses D/I for delivery/intraday, Angel uses DELIVERY/INTRADAY/CARRYFORWARD, Dhan uses CNC/INTRADAY/MARGIN). Symbols are stored canonically (NSE:RELIANCE, NFO:NIFTY24NOV2626200CE) and translated to each broker's instrument token or trading symbol through the broker's instrument master.

## Troubleshooting

- **Token expired** — reconnect the broker on Profile → Brokers; live deployments pause until the session is valid.
- **Order rejected: margin** — check funds and the margin required for short options; place hedge legs first.
- **Order rejected: price band** — limit prices must be within the exchange's dynamic price band; AlgoDesk also rejects limits far from the last traded price.
- **Order rejected: freeze quantity** — split large orders; AlgoDesk slices automatically.
- **F&O ban** — new positions in banned stocks are blocked by the exchange.

## Paper broker

The paper broker fills market orders at the live price plus configurable slippage (default 5 basis points), rests limit and stop orders until the price crosses, charges realistic Indian costs, enforces the same risk checks as live trading, and auto squares off MIS positions at 15:20 IST. It starts with ₹10,00,000 of virtual capital.
