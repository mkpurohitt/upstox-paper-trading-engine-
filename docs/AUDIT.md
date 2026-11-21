# Product audit

**Scope:** every page, every tab and the main user flows of AlgoDesk, run the way a new user runs it (fresh checkout,
`.env` copied from `.env.example`, no API keys, mock market data), plus a review of the numbers the product shows.
Each defect below was reproduced, fixed at the root, and, where possible, pinned with an automated test.

## How it was tested

| Check | Result after fixes |
|---|---|
| Automated crawl: log in as the demo user and as an admin, open all 21 routes and click every tab (58 tab views); record page errors, console errors and warnings, failed API calls and visible error text | 0 issues |
| Scripted user flows (21): copilot questions, backtest from chat, open a strategy and run a backtest, save a new strategy, Code/DSL/Visual editors, optimiser, Live page, place a paper order, screener, options builder, pairs, technical, "Ask AI" hand-off, news summary, all portfolio tabs, profile save, data export, kill-switch dialog, command palette, theme | 21/21 pass, 0 console or API errors |
| Python tests (`pytest`) | 124 passed (4 new regression tests, 2 extended) |
| Copilot evals | 131/131, score 1.000 |
| Playwright e2e (desktop + mobile) | 27 passed, 1 skipped by design |
| `ruff`, `mypy` (CI scope), `eslint --max-warnings=0`, `tsc`, `vitest`, production `next build` | all clean (mypy had 12 errors carried over from earlier phases, now 0) |
| Market-data sanity: index vs constituents, cross-asset correlations, implied vs realised volatility, intraday autocorrelation | see "Accuracy" |
| Strategy-engine sanity: zero-cost backtests on a driftless market must not make or lose money systematically | passes (it did not before) |

## Why "most tabs were not working" on a fresh Windows install

The pages themselves rendered, but the backend they call was unreachable or misconfigured. On a fresh install every page
that loads data failed:

1. **`DATABASE_URL` pointed at PostgreSQL** in `.env.example`. Without Docker there is no Postgres, so the API could not
   start or answered every request with an error. **Fix:** local runs default to SQLite at `<repo>/var/algo.db`, resolved
   against the repository root whichever folder you start from. Production refuses SQLite.
2. **Blank values in `.env` became empty strings** (`VAULT_MASTER_KEY=`, `LLM_PRIMARY_API_KEY=`, `COOKIE_DOMAIN=` …):
   an empty encryption key broke broker connections and 2FA, and the copilot believed an LLM was configured. **Fix:**
   blank means "use the default".
3. **`localhost` can resolve to IPv6 (`::1`) on Windows** while the API listens on IPv4, so the web app's `/api` proxy
   failed. **Fix:** the proxy and WebSocket default to `127.0.0.1`.
4. **The run instructions used Unix shell syntax** (`VAR=value cmd`, `trap`, `&`). **Fix:** one cross-platform
   launcher, `uv run python scripts/dev.py`. It creates `.env` if missing, installs JS dependencies, seeds the database,
   starts the API and web app, waits until both answer, and stops both on Ctrl+C. It also detects busy ports.
5. **Unix-only code paths:** the Python sandbox (custom indicators, Code mode) imported the POSIX-only `resource`
   module and started its child without `SYSTEMROOT`; dedicated services used `add_signal_handler`. **Fix:** guarded
   for Windows. Some scripts also read or wrote files without an explicit UTF-8 encoding; fixed.
6. **No feedback when the backend is down.** **Fix:** a banner on every page (and the login page) says the API is
   unreachable, says how to start it, and reconnects by itself. Proxy errors now read "Can't reach the AlgoDesk API"
   instead of "Request failed (500)".

## Defects found and fixed

### Functional

| # | Where | Defect | Fix |
|---|---|---|---|
| F1 | Portfolio → Overlap | HTTP 500 as soon as any deployment was active (`Deployment.name` does not exist) | Joins the strategy name; regression test |
| F2 | Live → Paper desk, strategies | Every new order was rejected by the daily loss limit on an account holding an old, underwater position: "day P&L" counted the whole unrealised loss since purchase | Day P&L marks carried positions from the previous close (broker convention); regression test |
| F3 | All error toasts from the risk engine | The message was a raw Python dict (`{'message': ..., 'decision': {...}}`) | Readable message; the decision goes into `details`. Validation errors name the field |
| F4 | Risk audit trail | Passing checks carried failure text ("platform kill switch engaged", passed = true) | Detail recorded only for failed checks |
| F5 | Login / sign-up | Submitting before the page finished loading sent the form as a GET: **email and password in the URL** and browser history | Native submission disabled until hydrated; `method="post"` |
| F6 | Build → Code / DSL | Editor loaded from a CDN (and a different Monaco version) and failed offline or behind a firewall with an unhandled error | Monaco served locally; plain-text fallback editor; DSL tab is now an editable, schema-validated JSON editor with Apply/Revert |
| F7 | Live → Strategies | A deployment whose runner crashed vanished from the tab with no message | Errored deployments stay listed with the error and a **Restart** button (paper/notify; live requires redeploying with 2FA); new endpoint and test |
| F8 | Paper trading | Market orders filled on weekends and at night | Outside exchange hours paper orders queue as after-market orders and fill at the next open; the ticket says so up front |
| F9 | Option dashboards | React warning: Select switching from uncontrolled to controlled | Select is always controlled; "Loading…" placeholder for expiries |
| F10 | Shell | WebSocket "closed before the connection is established" warning on every load | A socket that is still connecting is closed after it opens |
| F11 | Arbitrage scanner | Footer printed a literal `~cost_bps`; a negative "best net annualised" was shown in profit green; annualisation used whole days | Interpolated text, sign-aware colour, fractional days to expiry |
| F12 | Screener | Field labels showed a cryptic " ·F" suffix | " (fundamental)" |
| F13 | Dev builds | The floating Next.js badge covered the sidebar's Collapse button | Disabled (errors still show the overlay) |
| F14 | First launch | Portfolio, Live and the copilot's portfolio answers were empty | The demo seed adds a paper portfolio and two deployments |
| F15 | Visual builder | React Flow attribution hidden without a Pro subscription (licence notice) | Attribution shown |

### Accuracy (numbers the product shows)

| # | Area | Problem | Fix |
|---|---|---|---|
| A1 | Backtester | Trailing stops were ratcheted with a bar's high and then tested against the same bar's low. That assumes the high came first, and it biased every trailing-stop backtest. Zero-cost EMA crossover on a driftless market: t-stat −5.6 (should be ≈ 0). Seeded result: −₹1.22 L, Sharpe −15.9 | No look-ahead; the t-stat is now +1.6 (noise). Same strategy: −₹13.5 K with ₹19 K of real costs, Sharpe −1.2. Two regression tests |
| A2 | Option pricing | Theta ran on calendar time while prices only move during sessions, and implied vol sat below realised. Short straddles lost every day in backtests (−₹90 K in 6 weeks, Sharpe −14.6) | Business-time variance with an overnight gap share, quoted as calendar IV (NSE convention). Variance risk premium of ~10% over realised. The decay chart and the options builder's "days forward" now hold over weekends and bleed during sessions |
| A3 | Mock indices | NIFTY, SENSEX, Bank Nifty and sector indices were simulated independently of their stocks: NIFTY +7.3% over a year vs constituents −0.3%, and sector indices moving against the heatmap | Indices are cap-weighted composites of their constituents; stocks load on market + sector factors. Average pairwise correlation 0.24, NIFTY vol ≈ 13% |
| A4 | Mock live prices | Prices kept moving after the close while the header said "Market closed" | Prices stand at the last close when the exchange is closed |
| A5 | Portfolio → Performance | Equity curve and "winning days" used realised P&L only (every purchase day counted as a loss; price moves ignored) | Marked to market daily, today at live prices; adds max drawdown; best/worst day dated |
| A6 | Options builder | Margin estimate ignored hedges (₹1.43 L for a NIFTY iron condor) | Defined-risk structures charged at max loss plus exposure (₹40.7 K for the same condor); naked shorts by index/stock rate |

Results checked and found correct (no change needed): option chain (ATM straddle ≈ 0.8·S·σ·√T, ±1σ expected range,
max pain, PCR), NSE expiry calendar including holiday shifts (24 Nov 2026 Guru Nanak Jayanti → 23 Nov), NIFTY lot 65,
put-call parity, payoff breakevens and max loss, cost model totals, intraday return autocorrelation ≈ 0.

## What still needs a human before going live

These are not code defects. They are decisions and credentials only the operator can provide (see COMPLIANCE.md §9):
broker API keys and the static egress IP, exchange Algo-IDs, Razorpay live keys, an LLM API key, SEBI IA/RA status for
advice, legal pages (terms, privacy, grievance officer), and production secrets (`JWT_SECRET`, `VAULT_MASTER_KEY`).
Docker images were validated, but no Docker daemon was available to build them in the audit environment.
