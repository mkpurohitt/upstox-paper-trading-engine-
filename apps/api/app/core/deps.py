"""FastAPI dependencies: current user, role gates, 2FA step-up, rate limits."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.ratelimit import SlidingWindowLimiter
from algo_common.settings import get_settings
from algo_db.models import User
from app.core.db import get_db
from app.core.security import ACCESS, decode_token, verify_totp

bearer = HTTPBearer(auto_error=False)

# scope="function": commit happens before the response is sent, so clients never
# observe a 2xx for a write that is not yet durable.
DB = Annotated[AsyncSession, Depends(get_db, scope="function")]


async def get_current_user(
    db: DB, creds: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(creds.credentials, ACCESS)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", {"WWW-Authenticate": "Bearer"})
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def verify_step_up(db: AsyncSession, user: User, code: str | None) -> None:
    """Live-trading step-up: TOTP must be enabled *and* a fresh code supplied."""
    from algo_common.crypto import Vault

    if not user.totp_enabled or user.twofa is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Enable two-factor authentication to trade live")
    if not code:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A fresh 2FA code is required for live trading")
    secret = Vault.from_settings().decrypt(user.twofa.secret_enc, aad=f"user:{user.id}:totp")
    step = verify_totp(secret, code, user.twofa.last_used_step)
    if step is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid 2FA code")
    user.twofa.last_used_step = step
    await db.flush()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


_auth_limiter: SlidingWindowLimiter | None = None


async def auth_rate_limit(request: Request) -> None:
    global _auth_limiter
    if _auth_limiter is None:
        _auth_limiter = SlidingWindowLimiter(get_settings().auth_rate_limit_per_min, 60.0, prefix="rl:auth")
    ok, _ = await _auth_limiter.hit(client_ip(request))
    if not ok:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, slow down")


def idempotency_key(x_idempotency_key: str | None = Header(default=None)) -> str | None:
    return x_idempotency_key
