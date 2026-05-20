# API

Backend base URL: `http://localhost:8000`

Core endpoints:

- `GET /health`
- `GET /auth/login?mode=live`
- `GET /auth/login?mode=sandbox` returns sandbox guidance because sandbox tokens are generated in Developer Apps
- `GET /broker/connect`
- `GET /broker/callback?code=...` exchanges the auth code and saves the token into `.local/upstox_tokens.json`
- `GET /strategies`
- `POST /strategies/run/{strategy_id}`
- `POST /strategies/stop/{strategy_id}`
- `GET /signals`
- `POST /signals`
- `GET /orders`
- `GET /positions`
- `GET /pnl`
- `GET /capital`
- `PUT /capital`
- `GET /rms/events`
- `GET /reconciliation`
- `POST /market/subscribe`
- `GET /market/instruments`
- `GET /market/option-chain?instrument_key=...&expiry_date=YYYY-MM-DD`
- `GET /market/greeks`
- `GET /market/candles?instrument_key=...&unit=minutes&interval=1&to_date=YYYY-MM-DD&from_date=YYYY-MM-DD`
- `GET /dashboard/summary`

Websocket channels:

- `/ws/market-data`
- `/ws/strategy-events`
- `/ws/order-updates`
- `/ws/fill-updates`
- `/ws/pnl-updates`
- `/ws/rms-alerts`
- `/ws/reconciliation-events`
