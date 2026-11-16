"""Shared exception hierarchy."""

from __future__ import annotations


class AlgoError(Exception):
    """Base error. `code` is a stable machine readable identifier."""

    code = "error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class NotConfiguredError(AlgoError):
    code = "not_configured"
    status_code = 501


class ProviderError(AlgoError):
    code = "provider_error"
    status_code = 502


class RateLimitedError(AlgoError):
    code = "rate_limited"
    status_code = 429


class NotFoundError(AlgoError):
    code = "not_found"
    status_code = 404


class PermissionDeniedError(AlgoError):
    code = "permission_denied"
    status_code = 403


class ValidationFailedError(AlgoError):
    code = "validation_failed"
    status_code = 422


class RiskRejectedError(AlgoError):
    code = "risk_rejected"
    status_code = 409
