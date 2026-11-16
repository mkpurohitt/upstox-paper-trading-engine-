"""Sentry + OpenTelemetry bootstrap (both no-ops unless configured)."""

from __future__ import annotations

from fastapi import FastAPI

from algo_common.logging import get_logger
from algo_common.settings import get_settings

log = get_logger(__name__)


def init_sentry() -> None:
    s = get_settings()
    if not s.sentry_dsn:
        return
    import sentry_sdk

    def _scrub(event, _hint):  # type: ignore[no-untyped-def]
        req = event.get("request") or {}
        for k in ("cookies", "data"):
            req.pop(k, None)
        headers = req.get("headers") or {}
        for h in list(headers):
            if h.lower() in ("authorization", "cookie", "x-csrf-token"):
                headers[h] = "[redacted]"
        return event

    sentry_sdk.init(dsn=s.sentry_dsn, environment=s.environment, traces_sample_rate=0.1, before_send=_scrub,
                    send_default_pii=False)
    log.info("telemetry.sentry_enabled")


def init_otel(app: FastAPI) -> None:
    s = get_settings()
    if not s.otel_exporter_otlp_endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": s.otel_service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{s.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics,api/health")
    log.info("telemetry.otel_enabled", endpoint=s.otel_exporter_otlp_endpoint)
