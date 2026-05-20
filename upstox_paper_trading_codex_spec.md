# Upstox Live Paper Trading Platform — Codex Build Spec

## 1. Project Goal

Build a full-stack paper trading and strategy simulation platform that:

- consumes **live market data** from Upstox WebSocket / market data APIs
- uses **Upstox sandbox APIs** to simulate paper trading orders and portfolio/order operations
- allows **Python strategy files** to generate trade signals
- supports **equity, derivatives, commodity, currency**, and any other instrument classes available through the Upstox APIs configured in the app
- calculates and displays **live P&L**, **trade details**, **strategy details**, **virtual capital**, and **RMS / reconciliation data**
- lets the user edit virtual capital at runtime
- works as a proper research and execution environment for high-end trading strategies

The project must be built as a real production-style system, not a toy example.

---

## 2. Product Definition

### 2.1 Core user experience

The user should be able to:

1. connect Upstox live market data
2. connect Upstox sandbox for paper order execution
3. load one or more Python strategy files
4. subscribe each strategy to the instruments it needs
5. receive live signals from the strategy engine
6. route signals into sandbox paper orders
7. monitor live positions, P&L, fills, rejected orders, and order states
8. inspect strategy performance and RMS events
9. edit virtual capital and see updated drawdown, available buying power, and exposure
10. reconcile:
   - signal generated
   - order created
   - order sent
   - order accepted/rejected
   - fill received
   - position updated
   - P&L updated

---

## 3. Important Design Principle

This platform must use two separate layers:

### A. Market Data Layer
Used for live market ingestion and analytics.

### B. Execution Layer
Used for paper order placement via sandbox APIs.

Do **not** mix market data logic directly with order execution logic. Keep them separated so strategies can be tested safely and later switched to real brokers if needed.

---

## 4. Upstox Integration Requirements

### 4.1 Live data
Use Upstox live market data APIs and WebSocket feed for real-time data.

The system must support:
- latest traded price / close price updates
- bid/ask and market depth when available
- option Greeks when available
- option chain and instrument metadata
- historical candle data for indicators
- market status / session state

### 4.2 Sandbox execution
Use Upstox sandbox APIs for:
- placing paper orders
- modifying paper orders
- cancelling paper orders
- portfolio / position simulation where supported
- simulating order lifecycle states

### 4.3 Authentication
Support:
- OAuth login flow for normal API access
- long-lived analytics token for read-only market data, if available in the account/app configuration
- sandbox authentication where required

---

## 5. System Architecture

```text
+-------------------+       +-----------------------+
|  Python Strategy  | ----> |  Signal / Decision    |
|  Files / Plugins  |       |  Engine               |
+-------------------+       +-----------+-----------+
                                        |
                                        v
+-------------------+       +-----------------------+
| Upstox Live Feed  | ----> | Market Data Service   |
| WebSocket / APIs  |       | Indicators / Greeks   |
+-------------------+       +-----------+-----------+
                                        |
                                        v
+-------------------+       +-----------------------+
| Upstox Sandbox    | <---- | Paper OMS / Execution |
| Order APIs        |       | / Risk / Reconcile    |
+-------------------+       +-----------+-----------+
                                        |
                                        v
+---------------------------------------------------+
| Frontend Dashboard                                |
| trades | positions | pnl | rms | strategies | logs |
+---------------------------------------------------+
```

---

## 6. Recommended Tech Stack

### Backend
- Python 3.11+
- FastAPI
- Uvicorn
- WebSocket server / async event loop
- PostgreSQL for persistent storage
- Redis for streaming, pub/sub, and state caching
- Celery or APScheduler for background jobs if needed

### Strategy layer
- Python strategy plugins
- Pandas
- NumPy
- Optional: TA-Lib / vectorbt / backtrader / scipy

### Frontend
- Next.js or React
- TypeScript
- Tailwind CSS
- Recharts / lightweight chart library
- WebSocket client for real-time updates

### DevOps
- Docker
- Docker Compose
- Environment variables
- Optional: Nginx reverse proxy

---

## 7. Required Modules

## 7.1 Market Data Service
Responsibilities:
- connect to Upstox live market feed
- manage subscriptions by instrument key
- normalize incoming tick / quote / Greeks payloads
- publish data to Redis / internal event bus
- store historical snapshots if enabled
- expose internal APIs for strategies and frontend

Must support:
- LTPC stream
- full quote stream
- option Greeks stream
- OHLC candle retrieval
- instrument metadata lookup
- option chain lookup

## 7.2 Strategy Engine
Responsibilities:
- load Python strategy files dynamically
- run strategies independently
- provide each strategy only the data it subscribes to
- allow strategies to emit structured signals
- maintain per-strategy state
- support multiple strategies at once

A strategy must be able to declare:
- instrument universe
- timeframe
- required fields
- capital allocation
- risk settings
- execution preferences

## 7.3 Signal Router
Responsibilities:
- receive strategy signals
- validate signal schema
- check RMS rules
- attach strategy ID, timestamp, instrument, side, quantity, confidence, and reason
- route approved signals to execution engine
- log all rejected signals with reason

## 7.4 Paper OMS / Execution Engine
Responsibilities:
- convert signals into sandbox paper orders
- place, modify, and cancel sandbox orders
- track order IDs and exchange/broker responses
- maintain full order state machine
- simulate rejected / partial / filled states if the sandbox does not provide all states
- publish execution updates to frontend and database

## 7.5 RMS Engine
Responsibilities:
- pre-trade checks:
  - available virtual capital
  - margin usage
  - max position size
  - max loss per day
  - max trades per strategy
  - allowed instrument universe
  - allowed product type
  - order size limits
- post-trade checks:
  - realized/unrealized P&L
  - exposure
  - concentration
  - drawdown
  - stop-loss breaches
  - stale position detection
- generate alerts and RMS events

## 7.6 Reconciliation Engine
Responsibilities:
- compare strategy signal vs order sent vs order acknowledged vs order filled
- detect missing fills, delayed fills, duplicates, rejections, and mismatches
- maintain an audit trail for every trade lifecycle event

## 7.7 P&L Engine
Responsibilities:
- live mark-to-market P&L
- realized P&L
- unrealized P&L
- strategy-level P&L
- portfolio-level P&L
- instrument-level P&L
- day-wise summaries
- drawdown tracking

## 7.8 Virtual Capital Manager
Responsibilities:
- store editable starting capital
- allow intraday manual adjustment
- update available buying power
- support allocation by strategy and by account
- rebase P&L calculations when required

## 7.9 Frontend Dashboard
Responsibilities:
- live trading dashboard
- strategy monitoring
- trade and order blotter
- positions view
- P&L charts
- RMS alerts
- reconciliation view
- virtual capital editor
- instrument watchlist
- live logs / event stream

---

## 8. Strategy Plugin Contract

Every strategy file must implement a standard interface.

### Required interface

```python
class StrategyBase:
    strategy_name: str
    version: str

    def initialize(self, context): ...
    def on_market_data(self, tick, context): ...
    def on_bar(self, candle, context): ...
    def generate_signal(self, context): ...
    def on_order_update(self, order_event, context): ...
    def on_fill(self, fill_event, context): ...
    def shutdown(self, context): ...
```

### Strategy context must expose
- live market data cache
- historical candles
- instrument metadata
- option chain data
- Greeks data
- account / virtual capital
- current positions
- open orders
- risk limits
- logging utility
- signal emitter
- order intent creator

### Signal schema

```json
{
  "strategy_id": "strat_001",
  "timestamp": "2026-05-19T09:30:00+05:30",
  "instrument_key": "NSE_FO|....",
  "symbol": "NIFTY",
  "side": "BUY",
  "action": "OPEN",
  "order_type": "LIMIT",
  "product": "MIS",
  "quantity": 50,
  "limit_price": 123.45,
  "stop_loss": 10,
  "target": 20,
  "confidence": 0.82,
  "reason": "ATM breakout with delta confirmation",
  "metadata": {
    "greeks_used": true,
    "timeframe": "5m"
  }
}
```

---

## 9. Data Model

### Core database tables

#### users
- id
- email
- password_hash
- created_at

#### broker_connections
- id
- user_id
- provider_name
- access_token
- refresh_token
- sandbox_enabled
- created_at
- updated_at

#### strategies
- id
- user_id
- name
- version
- file_path
- enabled
- config_json
- created_at
- updated_at

#### strategy_runs
- id
- strategy_id
- status
- started_at
- stopped_at
- summary_json

#### market_ticks
- id
- instrument_key
- timestamp
- payload_json

#### candles
- id
- instrument_key
- timeframe
- timestamp
- open
- high
- low
- close
- volume
- payload_json

#### signals
- id
- strategy_id
- instrument_key
- timestamp
- signal_json
- status

#### orders
- id
- strategy_id
- signal_id
- broker_order_id
- instrument_key
- side
- order_type
- quantity
- price
- status
- raw_response_json
- created_at
- updated_at

#### fills
- id
- order_id
- fill_price
- fill_quantity
- fill_timestamp
- raw_response_json

#### positions
- id
- strategy_id
- instrument_key
- quantity
- avg_price
- ltp
- mtm
- realized_pnl
- unrealized_pnl
- updated_at

#### capital_accounts
- id
- user_id
- strategy_id
- starting_capital
- current_capital
- available_margin
- updated_at

#### rms_events
- id
- strategy_id
- event_type
- severity
- message
- event_json
- created_at

#### reconciliation_events
- id
- strategy_id
- signal_id
- order_id
- fill_id
- status
- details_json
- created_at

---

## 10. Frontend Pages

### 10.1 Login / connection setup
- connect Upstox
- enable sandbox
- set up strategy workspace

### 10.2 Live dashboard
- live market tiles
- strategy status
- open positions
- running P&L
- realized / unrealized P&L
- capital usage

### 10.3 Orders & trades
- all signals
- order status
- fill details
- rejection reasons
- timestamps
- broker response payload

### 10.4 Strategy monitor
- running strategies
- strategy logs
- signal frequency
- instruments subscribed
- last executed signal
- performance metrics

### 10.5 RMS dashboard
- margin usage
- max drawdown
- exposure
- stop-loss violations
- order rejects
- stale order checks
- daily risk summary

### 10.6 Reconciliation dashboard
- signal → order mapping
- order → fill mapping
- missing or delayed lifecycle steps
- audit trail search

### 10.7 Virtual capital editor
- edit starting capital
- add/remove capital
- reset capital
- allocate capital per strategy

### 10.8 Instrument explorer
- search instruments
- view option chain
- Greeks
- historical candles
- live LTP / quotes

---

## 11. Execution Flow

### Flow A: strategy signal to paper order

1. live feed updates arrive from Upstox
2. strategy consumes required data
3. strategy emits a signal
4. signal router validates the signal
5. RMS checks are run
6. signal is approved or rejected
7. approved signal is converted to a sandbox order request
8. sandbox order response is stored
9. order updates are streamed to frontend
10. fills update positions and P&L
11. reconciliation events are generated

### Flow B: manual paper trade
1. user places manual paper order from UI
2. order goes through the same paper OMS
3. risk checks are applied
4. order is executed in sandbox
5. P&L updates in real time

---

## 12. Risk Management Rules

Implement configurable rules like:

- maximum capital per strategy
- maximum intraday loss
- maximum overall portfolio loss
- maximum quantity per order
- maximum open positions
- maximum trades per day
- stop trading after X consecutive losses
- block orders during invalid market hours
- allow only listed instrument types
- allow only specific expiry / strike ranges
- block duplicate orders within a cooldown window

All risk rule breaches must be visible in the RMS dashboard.

---

## 13. Greeks and Derivatives Support

The system must expose Greeks in the strategy context and UI when available.

Store and show:
- delta
- gamma
- theta
- vega
- implied volatility if computed or available
- option chain metadata
- strike selection
- expiry selection

Strategies may request:
- ATM / ITM / OTM selection
- nearest expiry
- weekly/monthly expiry filtering
- multi-leg spreads
- hedge ratios
- delta-neutral basket construction

---

## 14. Strategy Examples to Support

The platform should make it easy to build:
- ATM straddles
- strangles
- hedged short straddles
- option Greeks-based hedges
- breakout systems
- mean reversion systems
- pair trading
- trend-following systems
- intraday volatility systems
- calendar spreads
- iron condors
- futures hedging for options positions

---

## 15. Logging and Audit Trail

Every event must be logged with:
- timestamp
- strategy ID
- event type
- instrument key
- request payload
- response payload
- decision reason

Keep an immutable audit trail for:
- signals
- order requests
- broker/sandbox responses
- fills
- cancellations
- RMS actions
- reconciliation actions

---

## 16. API Design

### Backend REST APIs
Create endpoints for:

- `/auth/login`
- `/broker/connect`
- `/broker/disconnect`
- `/strategies`
- `/strategies/run`
- `/strategies/stop`
- `/signals`
- `/orders`
- `/positions`
- `/pnl`
- `/capital`
- `/rms/events`
- `/reconciliation`
- `/market/instruments`
- `/market/option-chain`
- `/market/greeks`
- `/market/candles`
- `/dashboard/summary`

### WebSocket channels
- market-data stream
- strategy events
- order updates
- fill updates
- P&L updates
- RMS alerts
- reconciliation events

---

## 17. Suggested Folder Structure

```text
project-root/
  backend/
    app/
      api/
      core/
      data/
      execution/
      market/
      rms/
      reconciliation/
      strategies/
      models/
      services/
      utils/
    tests/
    main.py
    requirements.txt

  frontend/
    src/
      app/
      components/
      hooks/
      lib/
      pages/
      store/
      types/
    package.json

  strategies/
    sample_strategies/
      momentum_strategy.py
      option_greeks_strategy.py
      straddle_strategy.py

  infra/
    docker/
    nginx/
    postgres/

  docs/
    architecture.md
    api.md
    strategy_contract.md

  .env.example
  docker-compose.yml
  README.md
```

---

## 18. Sample Configuration

```yaml
app_name: upstox-paper-trading-platform
mode: paper
market_data_source: upstox_live
execution_source: upstox_sandbox
default_currency: INR
base_capital: 1000000

risk:
  max_loss_per_day: 20000
  max_position_size: 100000
  max_orders_per_minute: 20

strategies:
  auto_load: true
  hot_reload: true
```

---

## 19. Required Safety and Reliability Features

- never send a strategy order directly without RMS validation
- never execute sandbox order if data subscription is missing
- retries with exponential backoff for transient API failures
- store all raw responses
- support idempotency keys for order submission
- avoid duplicate execution on reconnect
- graceful reconnect for websocket drop
- heartbeat monitoring
- dead-letter queue for failed events
- rate-limit protection

---

## 20. Testing Requirements

### Unit tests
- strategy contract validation
- risk rules
- P&L calculations
- reconciliation logic
- order state transitions

### Integration tests
- live feed to strategy to signal
- signal to sandbox order
- fill to position update
- capital updates
- RMS rejection handling

### Simulation tests
- market data replay
- delayed feed
- rejected order
- partial fill
- duplicate signal
- reconnect recovery

---

## 21. Build Order for Codex

Codex must build the project in this order:

### Phase 1
- project scaffolding
- environment setup
- backend FastAPI skeleton
- frontend skeleton
- database schema

### Phase 2
- Upstox authentication
- live market feed integration
- sandbox order integration
- market data normalizer

### Phase 3
- strategy plugin system
- signal router
- RMS engine
- order lifecycle engine
- P&L engine

### Phase 4
- dashboard pages
- order blotter
- strategy monitor
- reconciliation UI
- capital editor

### Phase 5
- test coverage
- Dockerization
- docs
- sample strategies
- production hardening

---

## 22. Acceptance Criteria

The project is complete only when all of the following work:

- live market data streams into the system
- a Python strategy file can read the data and emit a signal
- the signal can be routed to sandbox paper order execution
- order lifecycle events appear in the UI
- positions and P&L update live
- virtual capital can be changed from UI and reflected in RMS
- RMS can block invalid orders
- reconciliation can show signal/order/fill mapping
- strategy-specific metrics are visible
- the system can run multiple strategies at once

---

## 23. Implementation Notes for Codex

1. Build it as a modular monorepo.
2. Keep strategy code isolated from execution code.
3. Make data ingestion asynchronous.
4. Make order execution idempotent.
5. Persist everything important in the database.
6. Provide sample strategies and sample seed data.
7. Provide a polished frontend with live charts and tables.
8. Make the whole app configurable from environment variables.
9. Add clear README and local setup instructions.
10. Ensure the app can be started with one command using Docker Compose.

---

## 24. Recommended Deliverables

- backend API server
- frontend dashboard
- database migrations
- strategy plugin system
- sandbox execution adapter
- market data adapter
- RMS engine
- reconciliation engine
- P&L engine
- sample strategies
- Docker Compose setup
- documentation

---

## 25. Final Objective

This project should function as a full live paper trading laboratory where:

- strategies consume real-time Upstox data
- sandbox handles simulated execution
- the UI displays everything live
- the user can test advanced options and multi-asset strategies
- RMS and reconciliation make the system trustworthy enough for serious research

