# Decisions log

Ambiguities in the brief, the option chosen, and why. Newest decisions are appended per phase.

## Phase 1 — scaffold

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Orphan branch.** The work branch was recreated as an empty orphan branch, as requested. `main` is untouched. | User asked for a new, empty branch. |
| 2 | **Product name "AlgoDesk".** | Neutral working name; set `APP_NAME` to rebrand (UI strings live in `apps/web`). |
| 3 | **uv workspace** for Python (`packages/py-common`, `packages/db`, `services/*`, `apps/api`) with a single lockfile. | Each service stays an importable, separately testable package, and there is one reproducible environment. |
| 4 | **One Python Docker image** runs every Python process (API, arq worker, market-data streamer, strategy runner); the process is chosen by the compose `command`. | Shared code with no version skew between services, and only one image to build. |
| 5 | **Shared DB layer `algo_db`** (`packages/db`) instead of each service owning tables. | Every service reads and writes the same Postgres schema, and Alembic needs a single metadata. |
| 6 | **`EMBEDDED_WORKERS`**: with no Redis, or when set true, the API process hosts the tick streamer, runners and jobs, and uses an in-memory bus/KV. | `make dev-lite`, the tests and the offline demo need no infrastructure. Compose sets it false. |
| 7 | **Refresh tokens are opaque, rotated and family-revoked**, kept in an httpOnly cookie on `/api/auth`. The CSRF double-submit cookie is required for refresh/logout. Access JWTs live in memory only. | OWASP guidance: they can't be read by XSS, refresh-token theft is detectable, and Bearer auth isn't CSRF-able. |
| 8 | **TOTP replay protection**: the last accepted time-step is stored, and the same code can't be used twice. | RFC 6238 §5.2. |
| 9 | **Audit log hash chain + Postgres trigger** blocking UPDATE/DELETE. | "Immutable audit log" requirement; tampering is detectable with `verify_chain()`. |
| 10 | **Next.js proxies `/api/*`** to FastAPI (same-origin cookies); WebSocket connects directly to the API (`NEXT_PUBLIC_WS_URL`). | Rewrites don't proxy WS upgrades reliably. |
| 11 | **Tailwind 3.4 + hand-written shadcn-style components.** | shadcn's CLI needs network access and prompts; the components are owned source anyway. |
| 12 | **Pinned frontend majors**: React 19, Next 15.5, Recharts 2, React Flow 12, zod 3, TS 5.9. | The brief specifies Next 15. Newer majors (TS 7, Recharts 3, React Flow 13) were avoided for stability. |
| 13 | **Python 3.12 in Docker; 3.13 also supported.** | The brief asks for 3.12. The local toolchain is 3.13; `requires-python >=3.12`. |

## Phase 2 — market data

| # | Decision | Rationale |
|---|----------|-----------|
| 14 | **Canonical symbols follow OpenAlgo-style naming** (`NFO:NIFTY24NOV2626200CE`, `NSE:RELIANCE`, `NSE_INDEX:NIFTY`). | It's the de-facto common format across Indian broker bridges, and the expiry is explicit in the symbol. |
| 15 | **Mock history = log-price Brownian bridge** between a 2019 anchor and a Nov-2026 anchor, correlated through a market factor (beta), with date-seeded continuation after that. Exact 1-minute paths for the last ~260 sessions; older days use a vectorised range model. | It's deterministic (the same symbol always gives the same history), realistic levels, and fast: the instrument master builds in ~1.4 s. |
| 16 | **Mock options = Black-Scholes on a VIX-linked skewed IV surface** with OI concentrated at round strikes (calls above spot, puts below). | It gives plausible PCR, max pain, skew and buildup patterns for the dashboards, the scanners and options backtests. |
| 17 | **Live provider errors are never silently replaced with mock data** (except the NSE MCP fallback, which is marked `source: mock`). | Showing synthetic prices as real would be misleading. |
| 18 | **Upstox proto** is reproduced from Upstox's public V3 feed schema and compiled with grpcio-tools (`protobuf>=7.35`). | Typed decoding. The `.proto` file documents the regeneration command. |
| 19 | **MCP SDK 2.x** (`streamable_http_client`), with a 1.x fallback path. | The installed SDK is 2.x; older environments are still supported. |
| 20 | **Tick demand model**: the WS gateway writes the symbol set plus heartbeats to KV and pings `md:control`; the streamer unions that with pinned symbols (strategy runners) and the always-on index strip. | Upstream subscriptions stay bounded by what clients actually watch, and it works across many API replicas. |
| 21 | **Market data timestamps are stored in UTC** (`TZDateTime` type). Intraday bars are displayed in IST on charts. | One source of truth; SQLite and Postgres behave identically. |

## Phase 3 — strategy engine

| # | Decision | Rationale |
|---|----------|-----------|
| 22 | **One declarative DSL (v1.0, Pydantic) drives every builder, the backtester and the live runner.** Code mode does not run user strategies: it runs a sandboxed *builder script* that emits DSL. | Prevents arbitrary code execution in the order path; a strategy behaves identically in research and live. |
| 23 | **Custom Python only inside `CUSTOM` indicators**, executed in a subprocess sandbox: AST allow-list, no imports/dunders/I-O attributes, `python -I -B`, empty env, `setrlimit` (CPU, memory, zero file writes) and a wall-clock timeout. | Covers the "advanced mode, sandboxed" requirement with defence in depth. Production should add seccomp / no-network (documented). |
| 24 | **Statutory charges are effective-dated regimes** (pre-Oct-2024, Oct-2024, Apr-2026). The Apr-2026 F&O STT rates follow the Union Budget 2026 proposal and are flagged *verify*. Brokerage tariffs are approximate per broker. | Backtests spanning regime changes are charged correctly; rates can be overridden with `set_rate_override()`. |
| 25 | **Intrabar execution is conservative**: if the stop and target are both touched in one bar, the stop fills first; gaps fill at the open; options SL is checked at the underlying's high/low extremes. | Avoids optimistic bias. |
| 26 | **Freeze-quantity order slicing** is modelled, and each slice is charged as a separate order. | Flat-fee brokerage on large F&O orders is otherwise understated. |
| 27 | **Options backtests price legs with Black-Scholes** (the mock IV surface in mock mode; realised vol + skew with live underlying data) unless chain snapshots exist. This is surfaced as a warning on every options result. | Tick-level historical option data is not freely available; being transparent about the modelling assumption matters more. |
| 28 | **Optimisation and walk-forward use the vectorised engine.** Overfitting checks: too few trades, IS-vs-OOS decay, neighbourhood fragility, and the deflated Sharpe ratio (Bailey & López de Prado). | Speed for parameter sweeps, plus actionable warnings rather than a single "best" number. |
| 29 | **Intraday backtest ranges are clipped** (e.g. 1m ≤ 60 days, 15m ≤ 400 days) with a warning. | Bounded memory and runtime, in line with broker history limits. |
| 30 | **Seeded demo strategies are not tuned to look profitable.** On random-walk mock data, naive strategies lose after costs. | Honest and educational; synthetic edges would be misleading. |
| 31 | **OpenAPI uses single (input-mode) schemas** and `openapi-typescript --default-non-nullable false`. | Fields with defaults stay optional in the generated TS types, so the DSL builder can send partial documents. |
| 32 | **Heavy builder panels (React Flow, Monaco, Recharts) are lazy-loaded** with `next/dynamic`. | Builder route first-load JS drops from 413 kB to 211 kB. |

## Phase 4 — broker gateway and risk

| # | Decision | Rationale |
|---|----------|-----------|
| 33 | **OpenAlgo (AGPL-3.0) was used only as a protocol reference.** No OpenAlgo code is copied, vendored or linked. All ten adapters are independent implementations of the brokers' publicly documented wire formats (endpoints, field names, checksum schemes), which are facts about third-party APIs. Details are in ARCHITECTURE.md → "Broker adapters & licensing". | Keeps the platform's own licence free of AGPL obligations while benefiting from OpenAlgo's catalogue of broker quirks (Kite weekly symbol codes, Dhan's `availabelBalance`, Noren `jData` bodies, Breeze checksum headers, ...). |
| 34 | **ICICI Breeze has no OpenAlgo module**, so it is implemented from ICICI's public Breeze docs (session token + `X-Checksum = sha256(ts + body + secret)`). | Explicitly requested in the brief. |
| 35 | **One `OrderRouter` for every order** (manual ticket, strategy runner, kill-switch square-off): Algo-ID tag → risk engine → freeze-qty slicing → persist → adapter → fills → audit → bus. | Pre-trade risk and the audit trail cannot be bypassed by any code path; system square-offs are tagged `bypass` and audited. |
| 36 | **The Algo-ID is a placeholder** (`ALGO_ID_PREFIX-S{strategy}` / `-MANUAL`) stored on every order and deployment and sent in broker tag fields. | Exchange-assigned Algo-IDs only exist after empanelment through a broker; the field and plumbing are ready for them. |
| 37 | **SEBI order-rate threshold**: a per-client, per-exchange 1-second sliding window (default 8/s, configurable, below the 10/s retail threshold), on top of per-user and per-strategy orders/minute limits. | SEBI retail algo framework. |
| 38 | **Exits are never blocked by loss limits**; kill switches block everything except the system square-off orders they issue themselves. | Users must always be able to reduce risk. |
| 39 | **Live mode requires TOTP 2FA**, checked before any broker is contacted, plus a fresh step-up code for each live deployment or manual live order. | Brief: "2FA required for live trading"; fail closed. |
| 40 | **The paper broker is DB-backed** (orders/trades tables, `mode='paper'`) with a polling matcher for resting orders and automatic 15:20 IST MIS square-off. | The paper account survives restarts, appears in Portfolio, and shares 100% of the router/risk code path with live trading. |
| 41 | **Broker credentials are AES-GCM encrypted with owner-bound AAD** (`user:{id}:broker:{name}`), never returned by the API, never audited; disconnecting erases them. | Brief §3 + OWASP A02. |
| 42 | **Live order sync polls order books** (`sync_live`), while broker postbacks/websockets remain an adapter override point. | Polling works uniformly across all ten brokers; push feeds are broker-specific. |
| 43 | **The live runner drains the bus in a separate pump task.** | Cancelling an async generator's `__anext__` (e.g. via `wait_for` timeouts) closes it. This was caught by the end-to-end deployment smoke test. |
