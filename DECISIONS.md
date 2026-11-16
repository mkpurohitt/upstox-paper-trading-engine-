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
