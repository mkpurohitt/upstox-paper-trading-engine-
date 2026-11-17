"""Render docs/API.md from the live OpenAPI schema (hand-written guide + generated endpoint tables).

Usage: uv run python apps/api/scripts/export_api_md.py docs/API.md
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LOG_LEVEL", "ERROR")

from app.main import create_app

PUBLIC = ("/api/health", "/api/auth/register", "/api/auth/login", "/api/auth/refresh", "/api/auth/demo", "/api/auth/providers",
          "/api/auth/google", "/api/billing/plans", "/api/billing/webhook", "/api/ai/shared/", "/api/auth/logout")
ADMIN = ("/api/admin/", "/api/rag/documents", "/api/rag/reindex-all", "/api/news/refresh")
TAG_ORDER = ["auth", "me", "health", "market", "analysis", "watchlists", "strategies", "backtests", "deployments", "orders", "brokers",
             "risk", "ai", "rag", "news", "portfolio", "billing", "account", "admin"]
TAG_TITLE = {"auth": "Authentication", "me": "Current user", "health": "Health", "market": "Market data", "analysis": "Analysis dashboards",
             "watchlists": "Watchlists", "strategies": "Strategies", "backtests": "Backtests", "deployments": "Deployments",
             "orders": "Orders, trades, positions & funds", "brokers": "Broker connections", "risk": "Risk & kill switch",
             "ai": "Copilot (AI)", "rag": "Knowledge base (RAG)", "news": "News & calendars", "portfolio": "Portfolio",
             "billing": "Billing & subscriptions", "account": "Account, privacy & notifications", "admin": "Admin console"}

GUIDE = """# AlgoDesk API

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
"""


def access(path: str) -> str:
    if path.startswith(PUBLIC) or path in PUBLIC:
        return "🔓"
    if path.startswith(ADMIN):
        return "🛡"
    return "👤"


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "docs/API.md"
    spec = create_app().openapi()
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            tag = (op.get("tags") or ["other"])[0]
            summary = (op.get("summary") or "").strip()
            desc = (op.get("description") or "").strip().split("\n")[0]
            text = desc if desc and len(desc) > len(summary) and not desc.startswith(summary) else summary
            groups[tag].append((method.upper(), path, text.replace("|", "\\|")))
    lines = [GUIDE]
    for tag in [t for t in TAG_ORDER if t in groups] + sorted(t for t in groups if t not in TAG_ORDER):
        lines.append(f"\n### {TAG_TITLE.get(tag, tag.title())}\n\n| | Method | Path | Description |\n|---|---|---|---|")
        for method, path, text in sorted(groups[tag], key=lambda x: (x[1], x[0])):
            lines.append(f"| {access(path)} | `{method}` | `{path}` | {text} |")
    n = sum(len(v) for v in groups.values())
    lines.append(f"\n_{n} operations across {len(spec['paths'])} paths._\n")
    with open(out, "w") as fh:
        fh.write("\n".join(lines))
    print(f"wrote {out} ({n} operations)")


if __name__ == "__main__":
    main()
