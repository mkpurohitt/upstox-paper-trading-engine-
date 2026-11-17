from __future__ import annotations

from typing import Any

import pyotp

from broker_gateway.base import BrokerAuthError


def resolve_totp(credentials: dict[str, Any], inputs: dict[str, Any] | None) -> str:
    """Use a one-time code from the user, or derive it from a stored TOTP seed."""
    code = (inputs or {}).get("totp")
    if code:
        return str(code).strip()
    seed = credentials.get("totp_secret")
    if seed:
        return pyotp.TOTP(str(seed).replace(" ", "")).now()
    raise BrokerAuthError("A TOTP code (or a stored TOTP secret) is required to log in")
