# Upstox Live Paper Trading Platform

Production-style paper trading lab for Upstox live market data, sandbox order execution, Python strategy plugins, RMS, reconciliation, P&L, and a React dashboard.

## Quick Start

1. Install Python 3.11+ and Node.js 20+.
2. In Upstox Developer Apps, create a live API app with this redirect URL exactly:

```text
http://localhost:8000/broker/callback
```

3. Create a sandbox Upstox API app with this redirect URL exactly:

```text
http://localhost:8000/broker/sandbox/callback
```

4. Edit `.env` and paste your Upstox credentials into:
   - `UPSTOX_LIVE_API_KEY`
   - `UPSTOX_LIVE_API_SECRET`
   - `UPSTOX_REDIRECT_URI`
   - `UPSTOX_SANDBOX_API_KEY`
   - `UPSTOX_SANDBOX_API_SECRET`
   - `UPSTOX_SANDBOX_REDIRECT_URI`
5. Start the full system:

```powershell
.\scripts\start_full_system.bat
```

This installs backend/frontend libraries, starts both servers, opens live login, opens sandbox login, and opens the dashboard.
It also downloads Upstox complete instruments files into `data/instruments` when `DOWNLOAD_INSTRUMENTS_ON_START=true`.

To stop everything:

```powershell
.\scripts\stop_full_system.bat
```

Open manually if needed:

- Frontend: `http://localhost:5173`
- Backend docs: `http://localhost:8000/docs`

8. Click `Live Login` in the dashboard. Upstox redirects back to the backend, and the backend saves the live access token at `.local/upstox_tokens.json`.

9. For sandbox, open Upstox Developer Apps, generate the sandbox access token, paste it into `UPSTOX_SANDBOX_ACCESS_TOKEN`, and restart the backend.

Local mode starts with simulated ticks so the dashboard, strategy engine, RMS, OMS, P&L, and reconciliation work before any broker token is added.

## Upstox Credentials

Use `.env`:

- `UPSTOX_LIVE_API_KEY`
- `UPSTOX_LIVE_API_SECRET`
- `UPSTOX_REDIRECT_URI`
- `UPSTOX_ACCESS_TOKEN` optional fallback only
- `UPSTOX_EXTENDED_TOKEN`
- `UPSTOX_SANDBOX_API_KEY`
- `UPSTOX_SANDBOX_API_SECRET`
- `UPSTOX_SANDBOX_REDIRECT_URI`
- `UPSTOX_SANDBOX_ACCESS_TOKEN`

After you click `Live Login` in the dashboard or open `GET /auth/login?mode=live`, Upstox redirects to `/broker/callback`. The backend exchanges the auth code and saves the live access token to `.local/upstox_tokens.json`.

Upstox sandbox currently uses a generated sandbox access token from the Sandbox app page, not the live OAuth login flow. Paste that generated token into `UPSTOX_SANDBOX_ACCESS_TOKEN`; future sandbox order calls use that token.

Instrument lookup:

- Local files: `data/instruments/complete.json` and `data/instruments/complete.csv`
- Refresh: `POST /market/instruments/refresh`
- Search: `GET /market/instruments/search?q=NIFTY&segment=NSE_INDEX`

Keep `ENABLE_ORDER_SUBMISSION=false` until you are ready to send sandbox order requests. When enabled, the paper OMS sends approved orders to the Upstox V3 order endpoint with the sandbox token.

## Current Implementation

- FastAPI backend with REST and websocket channels
- Upstox OAuth, market quote, historical candle, option chain, websocket-authorize, and sandbox V3 order adapters
- Strategy plugin loader and sample momentum strategy
- Signal router, RMS checks, paper OMS, simulated fills, position/P&L updates
- Reconciliation events for signal approval, rejection, order sent, and fill received
- React dashboard with live market tiles, strategy controls, capital editor, orders, positions, signals, RMS, reconciliation
- SQL schema matching the spec tables

## Upstox Docs Used

- OAuth authentication: `https://upstox.com/developer/api-documentation/authentication/`
- Sandbox: `https://upstox.com/developer/api-documentation/sandbox/`
- Place Order V3: `https://upstox.com/developer/api-documentation/v3/place-order/`
- Market quote: `https://upstox.com/developer/api-documentation/get-full-market-quote/`
- Market Data Feed V3: `https://upstox.com/developer/api-documentation/v3/get-market-data-feed/`
- Market Data Feed Authorize V3: `https://upstox.com/developer/api-documentation/get-market-data-feed-authorize-v3/`
- Historical Candle V3: `https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/`
- Option chain: `https://upstox.com/developer/api-documentation/get-pc-option-chain/`
