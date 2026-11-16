"""Structured JSON logging with automatic secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

_SENSITIVE_KEYS = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|totp|otp|pin|credential|cookie|vault)", re.I
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-_.=]+")


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _BEARER.sub(r"\1***", value)
    if isinstance(value, dict):
        return {k: ("***" if _SENSITIVE_KEYS.search(str(k)) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_redact_value(v) for v in value)
    return value


def redact_processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: mask any field whose key looks like a secret."""
    for key in list(event_dict.keys()):
        if key == "event":
            event_dict[key] = _redact_value(event_dict[key])
            continue
        if _SENSITIVE_KEYS.search(key):
            event_dict[key] = "***"
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = True, service: str = "algo") -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_processor,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, structlog.processors.StackInfoRenderer(), structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")
    for noisy in ("httpx", "httpcore", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
