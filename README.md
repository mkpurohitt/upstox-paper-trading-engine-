# AlgoDesk

AI-first algorithmic trading platform for Indian markets (NSE, BSE, MCX — cash, futures, options).

> Full documentation is completed in Phase 8. Quick start:

```bash
cp .env.example .env
make dev          # docker compose (postgres+timescale+pgvector, redis, api, workers, web)
# or, without Docker:
make install && make dev-lite
```

Open http://localhost:3000 and click **Try the demo account**.
