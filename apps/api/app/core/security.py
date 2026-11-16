"""Password hashing, JWT access tokens, opaque rotating refresh tokens, CSRF and TOTP."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from algo_common.settings import get_settings
from algo_common.timeutils import utcnow

_ph = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)

ACCESS = "access"
TWOFA_CHALLENGE = "2fa_challenge"
REFRESH_COOKIE = "algo_refresh"
CSRF_COOKIE = "algo_csrf"
CSRF_HEADER = "x-csrf-token"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(sub: int | str, token_type: str, ttl: timedelta, **claims: Any) -> str:
    s = get_settings()
    now = utcnow()
    payload = {
        "sub": str(sub),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
        **claims,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


def create_access_token(user_id: int, role: str, session_id: int | None, mfa: bool) -> str:
    s = get_settings()
    return create_token(
        user_id, ACCESS, timedelta(minutes=s.jwt_access_ttl_minutes), role=role, sid=session_id, mfa=mfa
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    s = get_settings()
    payload: dict[str, Any] = jwt.decode(
        token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]}
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_matches(cookie: str | None, header: str | None) -> bool:
    return bool(cookie and header and hmac.compare_digest(cookie, header))


# ---- TOTP (RFC 6238) ------------------------------------------------------------

def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().app_name)


def verify_totp(secret: str, code: str, last_used_step: int = 0) -> int | None:
    """Verify a code with ±1 step drift. Returns the matched time-step (for replay
    protection) or None."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(utcnow().timestamp()) // totp.interval
    for step in (now_step, now_step - 1, now_step + 1):
        if step <= last_used_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def new_recovery_codes(n: int = 8) -> tuple[list[str], list[str]]:
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]
    return codes, [hashlib.sha256(c.encode()).hexdigest() for c in codes]
