# Architecture

The platform is split into two hard boundaries:

- Market data layer: Upstox quote, historical candle, option chain, and websocket feed ingestion. Local mode starts with simulated ticks so the rest of the stack can be tested before live credentials are added.
- Execution layer: paper OMS, RMS, reconciliation, P&L, and a sandbox Upstox order adapter. Strategy code never calls the broker adapter directly.

Runtime flow:

1. Market data service publishes normalized ticks.
2. Strategy engine passes subscribed ticks into loaded Python strategy plugins.
3. Strategies emit `Signal` objects.
4. RMS validates missing subscriptions, quantity, confidence, and notional limits.
5. Paper OMS converts approved signals into Upstox V3 order payloads.
6. In local mode, fills are simulated; when `ENABLE_ORDER_SUBMISSION=true`, orders are sent using the saved Upstox sandbox token.
7. Fills update positions, P&L, virtual capital, and reconciliation events.
8. REST and websocket endpoints expose the state to the React dashboard.
9. The live OAuth callback stores the live Upstox access token in `.local/upstox_tokens.json`; the sandbox OMS adapter uses the generated sandbox token from `UPSTOX_SANDBOX_ACCESS_TOKEN`.

The database schema in `infra/postgres/001_schema.sql` mirrors the acceptance model from the build spec. The current backend uses an in-memory repository to keep local development fast; the SQL schema is ready for the next persistence pass.
