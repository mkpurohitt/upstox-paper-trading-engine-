# Compliance

This document maps the regulatory and security obligations relevant to an algorithmic trading platform for Indian retail investors
to what AlgoDesk implements in code, and lists what an operator still has to do. **It is not legal advice.** Regulations change;
items marked _verify_ must be confirmed against the latest SEBI / exchange circulars and statutes before going live.

## 1. Regulatory position

AlgoDesk is software. Live orders are placed **through the user's own SEBI-registered stock broker** using that broker's API. The
operator of an AlgoDesk deployment is typically one of:

* a **broker** offering algo tools to its clients, or
* an **algo provider / fintech empanelled with a broker** (an agent of the broker under SEBI's retail-algo framework), or
* an individual running the platform for their own account.

Each role carries different obligations; the platform is built so that the strictest case (empanelled provider) is supported.

## 2. SEBI framework for retail algorithmic trading

Reference: SEBI circular "Safer participation of retail investors in Algorithmic trading" (February 2025) and the NSE/BSE
implementation circulars that followed (phased implementation from late 2025, _verify_ current dates and formats).

| Requirement | Implementation | Operator action |
|---|---|---|
| Orders only through the broker's authenticated API; no open APIs | Live orders go through `BrokerAdapter`s using per-user OAuth/TOTP sessions (`services/broker-gateway`). There is no unauthenticated order path. | Register the app with each broker; keep API keys per user/vendor. |
| Static IP whitelisting | Documented egress design (ARCHITECTURE.md → Static egress IP); `EGRESS_STATIC_IP` is shown to users and reported by `/api/risk/limits`. | Provision a NAT gateway or egress proxy with a reserved IP; whitelist it with every broker. |
| Two-factor authentication | TOTP 2FA (RFC 6238 with replay protection) is required to enable live trading; every live deployment and live manual order needs a fresh code (step-up). | — |
| API session logout before the next trading session | Broker sessions expire daily; connections show status and require re-login; tokens are never refreshed silently past the broker's expiry. | — |
| Unique Algo-ID on every algo order | Every order and deployment carries `algo_id` (`ALGO_ID_PREFIX-S{strategy}` / `-MANUAL`), also sent in broker tag fields where supported. | Replace the placeholder prefix with exchange-assigned IDs after the algo is approved through your broker. |
| Order-per-second threshold for unregistered algos | Risk engine enforces a per-client, per-exchange 1-second window (`ORDER_RATE_LIMIT_PER_SEC`, default 8 < 10) plus per-minute user and strategy limits. | Register algos with the exchange if users need higher throughput. |
| Broker approval of each algo | Strategies are versioned (`strategy_versions`); each deployment stores the exact DSL and version it runs. | Submit strategies for approval through your broker. |
| White-box vs black-box | Strategies are white-box by default (DSL is fully disclosed). Black-box marketplace listings require the provider's **SEBI Research Analyst registration number** and stay hidden until an admin approves them (`/api/admin/strategies/review`); every decision is audited and the owner is notified. Deployment of an unapproved black-box strategy is refused. | Verify RA numbers on the SEBI intermediaries register; keep the research report per algo. |
| Kill switch | User kill switch (top bar) stops deployments, cancels orders and squares off paper positions. Admin global kill switch blocks every new order platform-wide and requires a reason. Both are audited and published on the bus. | Define who may use the global switch and when (see the runbook). |
| Pre-trade risk controls | `RiskEngine`: kill switches, exchange/instrument allow-lists, max qty/lots per order, max position value, orders per minute, orders per second, daily loss limit (exits always allowed), price-band sanity checks, exchange freeze-quantity slicing. | Tune defaults per user segment. |
| Audit trail | Append-only, hash-chained `audit_log` (Postgres trigger blocks UPDATE/DELETE) for orders, deployments, risk decisions, kill switches, admin actions, AI turns, consent changes and billing; `verify_chain` is available to admins. | Ship logs and DB backups to WORM storage; retain per section 6. |
| Grievance handling | Users can export their data, give feedback per AI answer, and see every order/risk decision. | Publish a grievance officer contact and SLA; brokers remain the principal for algo grievances. |

## 3. Investment advice, research and market abuse

* **SEBI (Investment Advisers) / (Research Analysts) Regulations.** Personalised buy/sell/hold recommendations require registration.
  The copilot runs with `ADVICE_ENABLED=false` by default: the system prompt forbids recommendations and price targets, the offline
  model answers advice requests with an explicit "I can't tell you whether to buy or sell…" plus objective data, and an output filter
  rewrites directive phrases ("you should buy", "strong buy", "guaranteed returns") and appends the disclaimer. Turning
  `ADVICE_ENABLED` on is only appropriate for an operator holding IA/RA registration.
* **Educational framing.** Every AI answer and every trading screen shows a risk disclaimer. SEBI's studies of FY22–FY24 found that a
  large majority of individual F&O traders lost money; backtests and paper trading are labelled as simulations and the backtester
  warns about overfitting.
* **SEBI (Prohibition of Fraudulent and Unfair Trade Practices) and (Prohibition of Insider Trading) Regulations.** The copilot refuses
  requests about spoofing, layering, front-running, circular/wash trading, pump-and-dump, trading on UPSI and evading surveillance
  (`guardrails.check_input`), and logs the attempt. The risk engine rejects limit prices far from the LTP.
* **No guaranteed returns** language anywhere in the product; marketing copy must follow the same rule.

## 4. Digital Personal Data Protection Act, 2023 (DPDP)

| Principle / right | Implementation |
|---|---|
| Notice & consent | Required consents (terms, privacy, data processing) are recorded at sign-up in an append-only `consents` ledger with IP and version; optional purposes (marketing, analytics, AI personalisation) default to off and can be toggled any time (Profile → Privacy). |
| Purpose limitation & minimisation | KYC stores only the last 4 characters of PAN; full PAN/Aadhaar, phone numbers, emails and secret-looking tokens are redacted from AI prompts before they reach any LLM provider; broker credentials are encrypted and never exported or logged. |
| Right to access | `GET /api/account/export` returns profile, consents, sessions, strategies and versions, backtests, deployments, orders, trades, chats, notifications, watchlists, screens, LLM usage and the user's audit entries as JSON. Every export is audited. |
| Right to correction | Profile details are editable; KYC can be resubmitted. |
| Right to erasure | `POST /api/account/delete` halts trading immediately and schedules erasure after a 7-day grace period (cancellable). The daily `purge_deleted_accounts` job deletes chats, broker credentials, notifications, watchlists, screens and sessions and pseudonymises the account (`deleted-{id}@deleted.invalid`). |
| Retention exception | Orders, trades and the audit trail are kept, linked to the pseudonymised account, because exchange/SEBI record-keeping obligations apply (DPDP s.17 exemptions for legal obligations). _Verify_ the retention period that applies to your role; brokers commonly retain records for at least 5–8 years. |
| Withdrawal of consent | Withdrawing the required data-processing consent is done by requesting deletion; optional consents can be withdrawn individually. |
| Security safeguards | See section 7. |
| Breach notification | Operator procedure: notify the Data Protection Board and affected users without delay as prescribed by the DPDP Rules; the audit log and request IDs support the investigation. |
| Cross-border transfer | Hosting region, LLM providers and embedding providers are configurable. For strict localisation, use an India-region deployment, Ollama (self-hosted) for the LLM and the hashing or a self-hosted embedder. |
| Children | The terms accepted at sign-up restrict use to adults; live trading additionally requires the broker's KYC. |

## 5. Payments (Razorpay)

* Card/UPI data never touches AlgoDesk servers: Razorpay Checkout collects payment details, so the platform stays out of PCI-DSS
  cardholder-data scope.
* Orders are created server-side with the plan's price; the client callback's signature (`HMAC_SHA256(order_id|payment_id)`) and the
  webhook signature (`HMAC_SHA256(body)`) are verified with constant-time comparison; activation is idempotent; failures are audited.
* Without keys (and never in production) checkout is simulated and clearly labelled.
* GST invoicing and refunds are operator responsibilities (Razorpay dashboard / accounting system).

## 6. Record keeping

| Record | Where | Retention guidance |
|---|---|---|
| Orders, fills, risk decisions, Algo-IDs | `orders`, `trades`, `audit_log` | Per broker/exchange rules for algo orders (_verify_; commonly ≥ 5 years). Never purged by DPDP deletion. |
| Strategy versions that ran live | `strategy_versions`, `deployments.dsl` | Same as orders (needed to explain any algo order). |
| Consents | `consents` (append-only) | For the life of the account + limitation period. |
| AI interactions | `chat_messages`, `llm_usage`, `audit_log` (`ai.chat` with prompt hash, tools, flags) | Chats are deleted on erasure; audit metadata is retained. |
| Payments | `payments` + Razorpay | Per tax law (_verify_; typically 8 years under the Income-tax / GST Acts). |

## 7. Security controls (summary)

Mapped loosely to OWASP ASVS L2:

* **Authentication & session:** Argon2id hashing, rotating refresh tokens with reuse detection, httpOnly cookies, CSRF double-submit,
  TOTP 2FA with replay protection, rate-limited auth endpoints, session list with revocation.
* **Access control:** every resource query is scoped by `user_id`; admin routes require `role=admin`; admins cannot demote themselves;
  shared chats are read-only, never include deployment/portfolio cards and can be revoked.
* **Cryptography:** AES-256-GCM vault with owner-bound associated data and key rotation for broker credentials and TOTP secrets; TLS
  everywhere in production; HSTS.
* **Input/output:** Pydantic validation on every endpoint; strict CSP; no HTML from users is rendered unsanitised (markdown rendering
  without raw HTML).
* **Sandboxing:** user Python runs in an isolated subprocess with an AST allow-list and resource limits; production workers should also
  run with seccomp/AppArmor and without network (ARCHITECTURE.md).
* **Supply chain:** pinned lockfiles (`uv.lock`, `pnpm-lock.yaml`); CI runs gitleaks, `pip-audit` and `pnpm audit`.
* **Logging:** JSON logs with request IDs; secret-looking fields are masked; immutable audit chain for security-relevant events.

## 8. AI governance

* **Model routing is transparent:** the provider and model that answered are stored with every message and shown in the UI; fallbacks
  are logged.
* **Grounding:** numbers come from tools, and answers cite knowledge-base sources with `[n]` markers. The eval suite (`evals/`, 131 cases)
  checks tool routing, refusals, citations and that numbers in answers match tool output; CI fails below 0.85.
* **Human in the loop:** the agent cannot place, modify or cancel orders; deployments require explicit UI confirmation with risk
  acknowledgement (and 2FA for live).
* **Prompt injection:** user-supplied, tool, document, news and dashboard content is treated as untrusted data, defanged and wrapped;
  attempts to extract the system prompt are refused and flagged.
* **Cost & abuse controls:** per-plan daily question quotas, token/cost tracking per user (`llm_usage`), per-IP rate limits.

## 9. Operator checklist before going live

1. Broker empanelment / agreements; register each algo and obtain exchange Algo-IDs; set `ALGO_ID_PREFIX`.
2. Static egress IP provisioned and whitelisted with every broker; `EGRESS_STATIC_IP` set.
3. `ADVICE_ENABLED=false` unless you hold SEBI IA/RA registration; review all marketing copy.
4. Privacy notice, terms, grievance officer and DPO contacts published; consent texts versioned.
5. Production secrets generated (`JWT_SECRET`, `VAULT_MASTER_KEY`, Razorpay, LLM keys) and stored in a secrets manager;
   `ENVIRONMENT=production` (disables one-click demo login and payment simulation); remove or re-password the seeded demo/admin users.
6. Backups (Postgres PITR) and log shipping to WORM storage; retention configured per section 6.
7. Worker hardening (seccomp/AppArmor, no network, read-only FS) and the kill-switch procedure rehearsed (docs/RUNBOOK.md).
8. Verify the effective-dated STT/charges regimes (`services/broker-gateway/broker_gateway/costs.py`, especially the Apr-2026 F&O STT
   regime flagged _verify_) against the enacted Finance Act.
9. Exchange market-data licensing settled before showing live prices to customers (section 10).

## 10. Market data licensing

Exchange prices are licensed data. An Upstox token gives **its account holder** API access to NSE/BSE/MCX data; showing that
data to *other* people (your customers) is redistribution, which the exchanges license separately (NSE/BSE data-vendor or
redistribution agreements, with per-user or per-terminal fees), and broker API terms commonly restrict data to the account
holder's own use. _Verify_ with Upstox and the exchanges before launch. Typical routes: each user connects their own broker
account and sees data fetched with their own token; or the operator signs a data-vendor agreement (directly or via a licensed
vendor) and reports users. The Charts terminal labels its source on every chart (LIVE / SIMULATED) so simulated data is never
presented as exchange data.
