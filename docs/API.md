# AlgoDesk API

Base URL: `http://localhost:8000` in development (the web app proxies `/api/*`). Interactive docs: `/docs` (Swagger UI) and
`/redoc`; the machine-readable schema is `/openapi.json`, from which `packages/api-client` (typed TypeScript client) is generated
with `make gen-api`.

## Authentication

* `POST /api/auth/register` or `POST /api/auth/login` returns a short-lived **access token** (JWT, ~15 min) in the body and sets a
  rotating **refresh token** in an `httpOnly`, `SameSite=Lax` cookie scoped to `/api/auth`, plus a readable `algo_csrf` cookie.
* Send the access token as `Authorization: Bearer <token>`.
* `POST /api/auth/refresh` (cookie + `X-CSRF-Token` header echoing `algo_csrf`) rotates the refresh token and returns a new access
  token. Reusing an already-rotated refresh token revokes the whole token family (theft detection).
* Google OAuth: `GET /api/auth/google/start` → Google → `/api/auth/google/callback`.
* **TOTP 2FA** is required for live trading; live orders and live deployments also need a fresh `totp_code` (step-up).

## Conventions

* JSON everywhere; timestamps are ISO-8601 with offsets (exchange times are IST, `+05:30`).
* Instruments use canonical symbols: `NSE:RELIANCE`, `NSE_INDEX:NIFTY`, `BSE_INDEX:SENSEX`, `NFO:NIFTY24NOV2626200CE`
  (`UNDERLYING + DDMMMYY + STRIKE + CE|PE`), `NFO:BANKNIFTY29DEC26FUT`, `MCX:CRUDEOIL…`.
* Errors: `{"error": {"code": "…", "message": "…", "details": …}}` with conventional status codes — 401 unauthenticated,
  403 forbidden, 404 not found, 409 rejected by the risk engine / conflict, 402 plan limit reached, 422 validation, 429 rate limited,
  503 a dependency is not configured.
* Rate limits: global per-IP limit (`API_RATE_LIMIT_PER_MIN`) and a stricter limit on auth endpoints; order placement additionally
  passes the risk engine's per-second (SEBI threshold) and per-minute order limits.
* Every response carries `X-Request-ID`; send your own to correlate logs.

## Streaming

### Copilot over SSE — `POST /api/ai/chat`

Body `{"message": "…", "session_id": 12 | null, "context": "<optional dashboard context>"}`; response `text/event-stream`, one JSON
object per `data:` line:

| event | payload |
|---|---|
| `start` | `session_id`, `user_message_id`, `title` |
| `delta` | `text` (append to the answer) |
| `tool_start` | `id`, `name`, `args` |
| `tool_end` | `id`, `name`, `ok`, `card` (UI card, see below), `error` |
| `replace` | `text` — the output filter rewrote the streamed answer |
| `done` | `session_id`, `message_id`, `content`, `citations[]`, `suggestions[]`, `cards[]`, `tools[]`, `flags[]`, `provider`, `model`, `usage` |
| `error` | `message` |

Card `type`s: `quotes`, `chart`, `option_chain`, `payoff`, `fundamentals`, `news`, `table`, `kv`, `screener`, `strategy`, `backtest`,
`deploy_confirm` (never starts trading — the client must call `POST /api/deployments`), `portfolio`, `portfolio_analysis`.

### WebSocket — `GET /ws`

First frame `{"type":"auth","token":"<access jwt>"}` → `{"type":"ready"}`. Then:

```jsonc
{"type": "subscribe", "channel": "ticks", "symbols": ["NSE:RELIANCE", "NSE_INDEX:NIFTY"]}   // -> {"type":"tick","data":{…}}
{"type": "subscribe", "channel": "orders"}          // own orders and fills
{"type": "subscribe", "channel": "deployments"}     // status, P&L and log lines of own deployments
{"type": "subscribe", "channel": "notifications"}   // in-app notifications
{"type": "subscribe", "channel": "backtest", "id": 42}
{"type": "chat", "message": "…", "session_id": null, "request_id": "r1"}  // -> {"type":"chat.event","request_id":"r1","event":{…}}
{"type": "ping"}
```

## Webhooks

`POST /api/billing/webhook` receives Razorpay events (`payment.captured`, `order.paid`, `payment.failed`), verified with
`X-Razorpay-Signature = HMAC-SHA256(body, RAZORPAY_WEBHOOK_SECRET)`.

## Endpoints

Legend: 🔓 public · 👤 signed-in user · 🛡 admin only. Generated from the OpenAPI schema by `apps/api/scripts/export_api_md.py`.


### Authentication

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `POST` | `/api/auth/2fa/disable` | Twofa Disable |
| 👤 | `POST` | `/api/auth/2fa/enable` | Twofa Enable |
| 👤 | `POST` | `/api/auth/2fa/setup` | Twofa Setup |
| 🔓 | `POST` | `/api/auth/demo` | One-click login as the seeded demo user (disabled in production). |
| 🔓 | `GET` | `/api/auth/google/callback` | Google Callback |
| 🔓 | `GET` | `/api/auth/google/start` | Google Start |
| 🔓 | `POST` | `/api/auth/login` | Login |
| 🔓 | `POST` | `/api/auth/login/2fa` | Login 2Fa |
| 🔓 | `POST` | `/api/auth/logout` | Logout |
| 🔓 | `GET` | `/api/auth/providers` | Providers |
| 🔓 | `POST` | `/api/auth/refresh` | Refresh |
| 🔓 | `POST` | `/api/auth/register` | Register |
| 👤 | `GET` | `/api/auth/sessions` | List Sessions |
| 👤 | `DELETE` | `/api/auth/sessions/{session_id}` | Revoke Session |

### Current user

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/me` | Me |
| 👤 | `PATCH` | `/api/me` | Update Me |

### Health

| | Method | Path | Description |
|---|---|---|---|
| 🔓 | `GET` | `/api/health` | Health |

### Market data

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/market/candles` | Candles |
| 👤 | `GET` | `/api/market/expiries` | Expiries |
| 👤 | `GET` | `/api/market/holidays` | Holidays |
| 👤 | `GET` | `/api/market/instruments/{symbol}` | Instrument |
| 👤 | `GET` | `/api/market/nse/tools` | Nse Tools |
| 👤 | `POST` | `/api/market/nse/tools/{name}` | Nse Tool Call |
| 👤 | `GET` | `/api/market/option-chain` | Option Chain |
| 👤 | `GET` | `/api/market/overview` | Overview |
| 👤 | `GET` | `/api/market/provider` | Provider |
| 👤 | `GET` | `/api/market/quote/{symbol}` | Quote |
| 👤 | `GET` | `/api/market/quotes` | Quotes |
| 👤 | `GET` | `/api/market/search` | Search |
| 👤 | `GET` | `/api/market/status` | Status |
| 👤 | `GET` | `/api/market/universes` | Universes |

### Analysis dashboards

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/analysis/arbitrage` | Arbitrage |
| 👤 | `GET` | `/api/analysis/fundamentals` | Fundamentals Dash |
| 👤 | `GET` | `/api/analysis/option-chain` | Option Chain |
| 👤 | `GET` | `/api/analysis/pairs` | Pairs Dash |
| 👤 | `GET` | `/api/analysis/pairs/scan` | Pairs Scan |
| 👤 | `POST` | `/api/analysis/payoff` | Payoff |
| 👤 | `GET` | `/api/analysis/quant` | Quant Dash |
| 👤 | `POST` | `/api/analysis/ratio-spreads` | Ratio Spreads |
| 👤 | `GET` | `/api/analysis/screener/fields` | Screener Fields |
| 👤 | `POST` | `/api/analysis/screener/run` | Screener Run |
| 👤 | `GET` | `/api/analysis/screens` | List Screens |
| 👤 | `POST` | `/api/analysis/screens` | Save Screen |
| 👤 | `DELETE` | `/api/analysis/screens/{screen_id}` | Delete Screen |
| 👤 | `PUT` | `/api/analysis/screens/{screen_id}` | Update Screen |
| 👤 | `GET` | `/api/analysis/straddle` | Straddle |
| 👤 | `GET` | `/api/analysis/technical` | Technical Dash |

### Watchlists

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/watchlists` | Lists |
| 👤 | `POST` | `/api/watchlists` | Create |
| 👤 | `DELETE` | `/api/watchlists/{wid}` | Delete |
| 👤 | `PUT` | `/api/watchlists/{wid}` | Update |

### Strategies

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/strategies` | List Strategies |
| 👤 | `POST` | `/api/strategies` | Create |
| 👤 | `GET` | `/api/strategies/code-template` | Code Template |
| 👤 | `POST` | `/api/strategies/compile-code` | Compile Code |
| 👤 | `GET` | `/api/strategies/dsl/schema` | Schema |
| 👤 | `GET` | `/api/strategies/indicators` | Indicators |
| 👤 | `GET` | `/api/strategies/templates` | Templates |
| 👤 | `POST` | `/api/strategies/validate` | Validate |
| 👤 | `DELETE` | `/api/strategies/{strategy_id}` | Delete |
| 👤 | `GET` | `/api/strategies/{strategy_id}` | Get |
| 👤 | `PUT` | `/api/strategies/{strategy_id}` | Update |
| 👤 | `POST` | `/api/strategies/{strategy_id}/clone` | Clone |
| 👤 | `PATCH` | `/api/strategies/{strategy_id}/listing` | Marketplace listing. Black-box listings require a SEBI RA registration |
| 👤 | `GET` | `/api/strategies/{strategy_id}/versions` | Versions |

### Backtests

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/backtests` | List Backtests |
| 👤 | `POST` | `/api/backtests` | Create |
| 👤 | `DELETE` | `/api/backtests/{backtest_id}` | Delete |
| 👤 | `GET` | `/api/backtests/{backtest_id}` | Get |
| 👤 | `GET` | `/api/backtests/{backtest_id}/trades` | Trades |

### Deployments

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/deployments` | List Deployments |
| 👤 | `POST` | `/api/deployments` | Deploy |
| 👤 | `GET` | `/api/deployments/{dep_id}` | Get Deployment |
| 👤 | `GET` | `/api/deployments/{dep_id}/logs` | Logs |
| 👤 | `POST` | `/api/deployments/{dep_id}/pause` | Pause |
| 👤 | `POST` | `/api/deployments/{dep_id}/restart` | Restart |
| 👤 | `POST` | `/api/deployments/{dep_id}/resume` | Resume |
| 👤 | `POST` | `/api/deployments/{dep_id}/square-off` | Square Off |
| 👤 | `POST` | `/api/deployments/{dep_id}/stop` | Stop |

### Orders, trades, positions & funds

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/funds` | Funds |
| 👤 | `GET` | `/api/orders` | Orders |
| 👤 | `POST` | `/api/orders` | Place |
| 👤 | `PATCH` | `/api/orders/{order_id}` | Modify |
| 👤 | `POST` | `/api/orders/{order_id}/cancel` | Cancel |
| 👤 | `GET` | `/api/positions` | Positions |
| 👤 | `POST` | `/api/positions/square-off` | Square Off |
| 👤 | `GET` | `/api/trades` | Trades |

### Broker connections

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/brokers/catalog` | Broker Catalog |
| 👤 | `GET` | `/api/brokers/connections` | Connections |
| 👤 | `POST` | `/api/brokers/connections` | Add Connection |
| 👤 | `DELETE` | `/api/brokers/connections/{conn_id}` | Disconnect |
| 👤 | `POST` | `/api/brokers/connections/{conn_id}/default` | Make Default |
| 👤 | `GET` | `/api/brokers/connections/{conn_id}/funds` | Funds |
| 👤 | `POST` | `/api/brokers/connections/{conn_id}/login` | Login |
| 👤 | `GET` | `/api/brokers/connections/{conn_id}/oauth-url` | Oauth Url |

### Risk & kill switch

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/risk/audit` | My Audit |
| 👤 | `POST` | `/api/risk/check` | Dry Run |
| 👤 | `GET` | `/api/risk/kill-switch` | Kill State |
| 👤 | `POST` | `/api/risk/kill-switch` | Kill |
| 👤 | `GET` | `/api/risk/limits` | Get Limits |
| 👤 | `PUT` | `/api/risk/limits` | Set Limits |

### Copilot (AI)

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `POST` | `/api/ai/chat` | Stream a copilot turn as Server-Sent Events |
| 👤 | `POST` | `/api/ai/messages/{message_id}/feedback` | Feedback |
| 👤 | `GET` | `/api/ai/sessions` | List Sessions |
| 👤 | `POST` | `/api/ai/sessions` | Create Session |
| 👤 | `DELETE` | `/api/ai/sessions/{session_id}` | Delete Session |
| 👤 | `GET` | `/api/ai/sessions/{session_id}` | Get Session |
| 👤 | `PATCH` | `/api/ai/sessions/{session_id}` | Patch Session |
| 👤 | `DELETE` | `/api/ai/sessions/{session_id}/share` | Unshare Session |
| 👤 | `POST` | `/api/ai/sessions/{session_id}/share` | Share Session |
| 🔓 | `GET` | `/api/ai/shared/{token}` | Public read-only view of a shared chat |
| 👤 | `GET` | `/api/ai/status` | Ai Status |
| 👤 | `GET` | `/api/ai/usage` | Ai Usage |

### Knowledge base (RAG)

| | Method | Path | Description |
|---|---|---|---|
| 🛡 | `GET` | `/api/rag/documents` | List Documents |
| 🛡 | `POST` | `/api/rag/documents/text` | Add Text |
| 🛡 | `POST` | `/api/rag/documents/upload` | Upload |
| 🛡 | `POST` | `/api/rag/documents/url` | Add Url |
| 🛡 | `DELETE` | `/api/rag/documents/{doc_id}` | Remove |
| 🛡 | `GET` | `/api/rag/documents/{doc_id}/chunks` | Chunks |
| 🛡 | `POST` | `/api/rag/documents/{doc_id}/reindex` | Reindex Doc |
| 🛡 | `POST` | `/api/rag/reindex-all` | Reindex All |
| 👤 | `POST` | `/api/rag/search` | Search Kb |

### News & calendars

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/news` | Feed |
| 👤 | `GET` | `/api/news/announcements` | Announcements |
| 👤 | `GET` | `/api/news/calendar` | Calendar |
| 🛡 | `POST` | `/api/news/refresh` | Refresh |
| 👤 | `GET` | `/api/news/sentiment` | Sentiment Overview |
| 👤 | `GET` | `/api/news/{news_id}` | Item |
| 👤 | `POST` | `/api/news/{news_id}/summarize` | Summarize Item |

### Portfolio

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/portfolio/dividends` | Upcoming corporate actions for held stocks, with estimated dividend cash flow. |
| 👤 | `GET` | `/api/portfolio/overlap` | Instruments shared by more than one active deployment (hidden concentration across strategies). |
| 👤 | `GET` | `/api/portfolio/performance` | Paper-account performance marked to market daily: equity curve, daily P&L, winning days and XIRR. |
| 👤 | `GET` | `/api/portfolio/summary` | Summary |

### Billing & subscriptions

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `POST` | `/api/billing/cancel` | Cancel |
| 👤 | `POST` | `/api/billing/checkout` | Checkout |
| 🔓 | `GET` | `/api/billing/plans` | Plans |
| 👤 | `POST` | `/api/billing/resume` | Resume |
| 👤 | `POST` | `/api/billing/simulate` | Dev/test only: complete a simulated checkout (no Razorpay keys) |
| 👤 | `GET` | `/api/billing/subscription` | Subscription |
| 👤 | `POST` | `/api/billing/verify` | Verify |

### Account, privacy & notifications

| | Method | Path | Description |
|---|---|---|---|
| 👤 | `GET` | `/api/account/consents` | Consents |
| 👤 | `POST` | `/api/account/consents` | Set Consent |
| 👤 | `POST` | `/api/account/delete` | Request Deletion |
| 👤 | `POST` | `/api/account/delete/cancel` | Cancel Deletion |
| 👤 | `GET` | `/api/account/export` | Download all personal data (DPDP right to access) |
| 👤 | `GET` | `/api/account/kyc` | Kyc Status |
| 👤 | `POST` | `/api/account/kyc` | Submit Kyc |
| 👤 | `GET` | `/api/notifications` | Notifications |
| 👤 | `POST` | `/api/notifications/read-all` | Mark All Read |
| 👤 | `POST` | `/api/notifications/test` | Test Notification |
| 👤 | `POST` | `/api/notifications/{notification_id}/read` | Mark Read |

### Admin console

| | Method | Path | Description |
|---|---|---|---|
| 🛡 | `GET` | `/api/admin/audit` | Audit Log |
| 🛡 | `GET` | `/api/admin/audit/verify` | Audit Verify |
| 🛡 | `GET` | `/api/admin/health` | Health |
| 🛡 | `GET` | `/api/admin/kill-switch` | Get Kill |
| 🛡 | `POST` | `/api/admin/kill-switch` | Post Kill |
| 🛡 | `GET` | `/api/admin/payments` | Payments |
| 🛡 | `GET` | `/api/admin/stats` | Stats |
| 🛡 | `GET` | `/api/admin/strategies/review` | Review Queue |
| 🛡 | `POST` | `/api/admin/strategies/{strategy_id}/review` | Review |
| 🛡 | `GET` | `/api/admin/subscriptions` | Subscriptions |
| 🛡 | `GET` | `/api/admin/users` | Users |
| 🛡 | `PATCH` | `/api/admin/users/{user_id}` | Patch User |

_163 operations across 141 paths._
