"""Prometheus metrics shared by all services (exposed at /metrics)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP latency", ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
WS_CONNECTIONS = Gauge("ws_connections", "Open WebSocket connections")
TICKS_PUBLISHED = Counter("ticks_published_total", "Ticks published to the bus", ["provider"])
ORDERS_PLACED = Counter("orders_placed_total", "Orders routed to brokers", ["broker", "mode", "status"])
RISK_DECISIONS = Counter("risk_decisions_total", "Risk engine decisions", ["decision", "rule"])
BACKTESTS = Counter("backtests_total", "Backtests executed", ["kind", "status"])
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens", ["provider", "model", "direction"])
TOOL_CALLS = Counter("agent_tool_calls_total", "Agent tool calls", ["tool", "status"])
ACTIVE_DEPLOYMENTS = Gauge("active_deployments", "Running strategy deployments", ["mode"])
KILL_SWITCH = Gauge("kill_switch_engaged", "Global kill switch state (1 = engaged)")
