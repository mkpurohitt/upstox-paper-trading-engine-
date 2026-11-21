# Operations runbook

## Deploying

1. Build the images: `docker compose build` (one Python image for api/worker/market-data/strategy-runner, one for web).
2. Provide configuration through a secrets manager or an `.env` file based on `.env.example`. At minimum, for production:
   `ENVIRONMENT=production`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET` (≥ 48 random bytes), `VAULT_MASTER_KEY` + `VAULT_KEY_ID`,
   `CORS_ORIGINS`, `COOKIE_SECURE=true`, `API_BASE_URL`, `WEB_BASE_URL`, `NEXT_PUBLIC_WS_URL`, plus whichever integrations you use (Upstox, LLM, Razorpay, NSE MCP, SMTP,
   Telegram).
3. Run migrations: the `migrate` service runs `alembic upgrade head && python -m app.seed` (the seed is idempotent and also loads the
   knowledge base). Then start the stack: `docker compose up -d`.
4. Put a TLS-terminating reverse proxy in front of `web` (and `api` for WebSockets, or route `/ws` to the API).
5. Route broker-bound traffic through the static egress IP (ARCHITECTURE.md → Static egress IP) and set `EGRESS_STATIC_IP`.
6. Smoke test: `GET /api/health`, log in, open Admin → Health (every check green), place a paper order, run a backtest, ask the copilot
   a question.

## Configuration switches you will use

| Variable | Effect |
|---|---|
| `DATA_MODE=mock\|live` | Mock market data (deterministic, offline) vs Upstox. Live also enables RSS news ingestion. |
| `EMBEDDED_WORKERS` | `true` runs streamer, runners, matcher and scheduler inside the API (single-process dev). Use `false` with dedicated containers. |
| `LLM_PRIMARY_*`, `LLM_FALLBACKS`, `OLLAMA_ENABLED` | Copilot model chain. With nothing configured, the offline assistant answers. |
| `LLM_PRICING_JSON` | USD per 1M input/output tokens per model, for cost tracking. |
| `ADVICE_ENABLED` | Keep `false` unless you hold SEBI IA/RA registration (COMPLIANCE.md §3). |
| `ORDER_RATE_LIMIT_PER_SEC` | Per-client per-exchange orders/second ceiling (default 8; SEBI threshold is 10). |
| `ALGO_ID_PREFIX` | Prefix for Algo-ID tags until exchange-assigned IDs are available. |
| `RAZORPAY_KEY_ID/SECRET/WEBHOOK_SECRET` | Payments; test keys start with `rzp_test_`. Without keys, checkout is simulated (non-production only). |
| `PAPER_MARKET_HOURS` | `true` (default): paper orders placed while the exchange is closed queue as after-market orders and fill at the next open. `false` fills at any hour (used by the test suites). |
| `REDIS_URL=none` | Forces the in-process bus/cache even if a Redis URL is set elsewhere (single-process runs). |

## Kill switch procedure

**User-level:** users press **Kill switch** in the top bar. This stops their deployments, cancels open orders and squares off paper
positions. Live positions are squared off through the broker where the adapter supports it; users must verify in their broker
terminal.

**Platform-level (admins):** Admin → Kill switch → *Engage*, with a reason. Effect: every new order for every user is rejected
(`platform kill switch engaged`), all running deployments stop, and optionally all positions are squared off. Use it for:

* exchange or broker outages producing inconsistent fills;
* a strategy behaving abnormally across many users (duplicate orders, runaway loops);
* a suspected security incident (credential leak, unauthorised access);
* regulator or broker instruction.

After the cause is resolved, release it with a reason. Deployments do **not** restart automatically; users restart them from the Live
page. Every engage/release is in the audit log (`killswitch.global`).

## Routine tasks

| Task | How |
|---|---|
| Verify audit integrity | Admin → Audit → *Verify chain* (or `GET /api/admin/audit/verify`). Investigate any break immediately. |
| Rotate the vault key | Generate a new key, set it as `VAULT_MASTER_KEY` with a new `VAULT_KEY_ID`, move the old one to `VAULT_PREVIOUS_KEYS`, restart, then re-encrypt (`Vault.rotate()` over broker connections and 2FA secrets). Remove the old key afterwards. |
| Rotate JWT secret | Changing `JWT_SECRET` invalidates access tokens (users silently refresh); refresh tokens are opaque DB records and survive. |
| Re-index the knowledge base | Admin → Knowledge base → *Re-index all*. Required after changing `EMBEDDING_PROVIDER`/`EMBEDDING_MODEL`; documents with an outdated index version are also re-indexed on startup. |
| Add knowledge | Admin → Knowledge base: upload PDF/HTML/Markdown, add a URL or paste text. Check retrieval with *Test retrieval*. |
| Refresh news now | Admin → Overview → *Refresh news now* (otherwise every 15 minutes). |
| Review black-box listings | Admin → RA reviews. Verify the RA number on the SEBI intermediaries register before approving. |
| Change a user's plan / role | Admin → Users. All changes are audited. |
| Account deletions | Automatic: `purge_deleted_accounts` runs daily and erases personal data 7 days after a request. |
| Update statutory charges | Edit the effective-dated regimes in `services/broker-gateway/broker_gateway/costs.py` (or set overrides) when a Finance Act or exchange circular changes rates. |

## Monitoring and alerts

* `/metrics` (Prometheus): alert on `http_requests_total{status=~"5.."}` rate, p95 latency, `risk_decisions_total{decision="reject"}`
  spikes, `orders_placed_total{status="rejected"}` by broker, `kill_switch_engaged == 1`, `ws_connections` dropping to 0 during market
  hours, and `llm_tokens_total` growth against budget.
* Admin → Health shows live checks for the database, cache/bus, market data, NSE MCP, LLM providers, jobs and WebSockets.
* Logs are JSON with `request_id`; search by request ID from a user's error report.

## Backups and recovery

* Postgres: continuous archiving / PITR (or managed database snapshots) with at least daily restore tests. The audit log must be
  included; restore integrity can be confirmed with *Verify chain*.
* Redis holds only transient state (bus, rate-limit windows, caches, job queue); it can be flushed safely outside market hours.
* Recovery order: database → API → workers/runners → web. Running deployments resume from the database on runner start; reconcile
  live positions against the broker before re-enabling strategies.

## Incident response

1. Contain: engage the platform kill switch if trading safety is at risk; revoke compromised sessions (users can revoke their own;
   admins can deactivate users).
2. Preserve evidence: export audit entries and logs for the time window; do not modify the database by hand (the audit trigger blocks
   it anyway).
3. Assess personal-data impact and notify the Data Protection Board and affected users as required by the DPDP Rules; notify brokers
   and exchanges where trading was affected.
4. Post-mortem with action items; add a regression test or eval case.
