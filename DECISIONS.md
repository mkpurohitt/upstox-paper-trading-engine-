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

## Phase 5 — analysis dashboards

| # | Decision | Rationale |
|---|----------|-----------|
| 44 | **Analytics live in `strategy_engine.analytics`** (options, technical, fundamentals, quant, pairs, screener) as pure async functions over a `MarketDataProvider`; the API layer only validates and caches. | The same functions back the dashboards, the AI agent tools (Phase 6) and the screen-alert job, so numbers agree everywhere. |
| 45 | **Payoff maths exists twice**: server-side (`analytics.options.payoff`, with POP and Greeks) and client-side (`lib/options.ts`, Black-Scholes, unit-tested against the same invariants). | Sliders (days forward, IV shift, price range) must respond instantly without a round trip; the server stays the source of truth for POP and Greeks. |
| 46 | **Chain IVs are computed against the forward**, and arbitrage scans report gross and net-of-cost figures with an explicit `cost_bps` input. | Avoids phantom put-call-parity "violations" caused by carry; makes cost assumptions visible. |
| 47 | **Fundamentals are clearly labelled `source: "mock"`** until a fundamentals vendor is configured (Upstox/NSE do not provide audited financials). The UI shows a "sample data" badge. | Never present synthetic numbers as real. |
| 48 | **Saved screens store the full query**; alerting screens are re-run every 5 minutes by `run_screen_alerts` (embedded scheduler or arq cron), which notifies only on *new* matches. | Avoids repeat notifications; the per-plan `screens` quota is enforced on save. |
| 49 | **Options structures can be sent to the Builder** as an options-DSL draft with ATM-relative strikes, and paper-traded as a basket (hedges first). | Closes the loop analysis → backtest → deploy; ATM-relative strikes make the backtest meaningful across dates. |
| 50 | **The straddle decay curve switches to hourly steps under 3 days to expiry**; the payoff chart's default price range scales with the expected move (≈4σ). | On weekly-expiry days a daily grid gives a two-point line and a fixed ±8% range hides the payoff shape. |

## Phase 6 — AI layer, copilot and evals

| # | Decision | Rationale |
|---|----------|-----------|
| 51 | **"GPT-6 Luna" is reached through a generic OpenAI-compatible client** (`LLM_PRIMARY_BASE_URL`, `LLM_PRIMARY_API_KEY`, `LLM_PRIMARY_MODEL`), sending `max_completion_tokens` and falling back to `max_tokens` for older compatible servers. Anthropic and Ollama are fallbacks (`LLM_FALLBACKS`); a rule-based offline model is always last. | No vendor SDK lock-in; any compatible gateway works. The offline model keeps the product and CI usable without keys. |
| 52 | **Sharpe and Sortino use rf = 0 by default** (`BacktestParams.risk_free`). | The simulation pays no interest on idle cash, so subtracting 6.5% from a low-exposure strategy's returns produced Sharpe ratios around −9 for nearly flat equity curves. rf = 0 is the pyfolio/quantstats convention; it stays configurable. |
| 53 | **The router fails over only before any output is streamed**, and opens a 60-second circuit for a failed provider. | Switching models mid-answer would produce incoherent text; the circuit avoids paying timeout latency on every request while a provider is down. |
| 54 | **Cheap/strong routing is a transparent heuristic** (length, research/strategy keywords, dashboard context). | Predictable and cheap; per-plan quotas cap total usage. |
| 55 | **Tools return two payloads: compact JSON for the model and a UI card.** Cards render deterministically from data, never from model text. | Numbers on screen come from tools, not from model paraphrase; the model's context stays small. |
| 56 | **`deploy_strategy` only prepares a deployment.** Confirmation happens in the UI through the normal `/api/deployments` endpoint, which needs explicit risk acknowledgement, and live mode needs a broker connection plus a fresh 2FA code. Shared chats never expose deployment or portfolio cards. | §4: "deploy_strategy always needs explicit UI confirmation". The agent has no path to place orders. |
| 57 | **Hybrid retrieval: dense (pgvector or in-memory) + BM25 → reciprocal-rank fusion → lexical/semantic reranker with an absolute relevance gate**, at most two chunks per document. The default embedder is deterministic feature hashing (offline); OpenAI-compatible and Ollama embedders are configurable. Documents carry an `index_version`, and outdated ones are re-indexed on startup. | Works offline and in CI. The relevance gate stops off-topic questions from citing random documents. Versioning keeps stored vectors consistent when tokenisation or embedders change. |
| 58 | **Guardrails run in code before and after the model**: market-abuse refusals, prompt-injection detection (a request to reveal the system prompt is refused outright), PII/secret redaction before any provider call, untrusted wrapping and defanging of tool output, RAG chunks, news and dashboard context, and an advice filter when `ADVICE_ENABLED=false`. Every turn is audited with a prompt hash, tools, flags and tokens. | Defence in depth: the system prompt alone is not a control. |
| 59 | **Chat streams over SSE (`POST /api/ai/chat`) and over the existing WebSocket** (`{"type":"chat"}`), both driven by the same `run_turn` event generator. The web app uses SSE. | SSE survives proxies, needs no extra connection state and is easy to cancel; the WebSocket path serves clients that already hold a socket. |
| 60 | **Follow-ups ("backtest it", "deploy it") resolve against a compact digest of earlier tool results** appended to assistant turns in the history. | Real models need the prior DSL in context to call tools correctly; the offline model uses the same digest. |
| 61 | **Expiring contracts roll forward at the close** (`expiry_from_date`: 15:30 IST for NSE/BSE, 23:30 for MCX). | After 15:30 on an expiry day the chain previously showed the expired contract with zero time value (found by a test run in the evening). |
| 62 | **The evals use deterministic checks** (tool routing, arguments, cards, citations, flags, grounding of numbers) rather than LLM-as-judge. | Reproducible in CI and cheap. A judge model can be layered on for `--provider configured` runs. |

## Phase 7 — news, portfolio, profile, billing, admin

| # | Decision | Rationale |
|---|----------|-----------|
| 63 | **News ingestion uses RSS only in `DATA_MODE=live`**; mock mode uses a deterministic, clearly labelled offline generator plus NSE MCP filings. AI summaries run for at most 8 new articles per refresh (the rest on demand); without an LLM, summaries are extractive and sentiment is lexicon-based. | Bounded LLM cost, a working offline demo, and synthetic headlines are never shown as real news ("sample" badges, `.invalid` URLs are not linked). |
| 64 | **The economic calendar is an indicative schedule** of recurring releases (CPI on the 12th, RBI MPC decisions in even months, GDP at quarter-end+2, FOMC, etc.), labelled as such in the API and the UI. | No free official machine-readable source covers all of these; mislabelling them as confirmed dates would mislead. |
| 65 | **Portfolio consolidation isolates each broker**: one failing adapter (expired token, API outage) shows an error on its account chip and never breaks the page. Paper CNC longs are shown as holdings; XIRR treats the paper starting capital as the only contribution. | Real-world broker sessions expire daily. |
| 66 | **Razorpay: orders, client-signature verification and a webhook all converge on one idempotent `_mark_paid`.** Without keys (and never in production) checkout is simulated through `/api/billing/simulate`. Invalid signatures are committed as `failed` and audited before the 400 is returned. | Webhooks can arrive before or after the browser callback. Forged-signature attempts must leave a trace. |
| 67 | **DPDP deletion = immediate trading halt + 7-day grace + purge job.** The purge erases personal data (chats, broker credentials, notifications, watchlists, screens, sessions, identifiers) and keeps orders, trades and the audit trail linked to a pseudonymised account. | Users get erasure and a chance to cancel; exchange/SEBI record-keeping obligations take precedence for trading records (DPDP s.17). |
| 68 | **KYC is a placeholder that stores only the PAN's last four characters.** | Brokers perform KYC for live trading; holding full PANs would add risk without a use. |
| 69 | **Muted notification events still create in-app records** but skip email/Telegram/WhatsApp. | Users can always audit what happened; muting only controls interruptions. |
| 70 | **The admin global kill switch requires a reason** (stored in the flag and the audit log); admins cannot demote or deactivate themselves; black-box approvals notify the owner. | Accountability for platform-wide actions; avoids locking the last admin out. |
