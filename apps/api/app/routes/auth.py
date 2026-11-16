"""Authentication: email/password, Google OAuth, TOTP 2FA, rotating refresh sessions."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update

from algo_common.crypto import Vault
from algo_common.kv import get_kv
from algo_common.settings import get_settings
from algo_common.timeutils import utcnow
from algo_db.audit import audit
from algo_db.models import Session, User, UserTwoFA
from app.core.deps import DB, CurrentUser, auth_rate_limit, client_ip
from app.core.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    REFRESH_COOKIE,
    TWOFA_CHALLENGE,
    create_access_token,
    create_token,
    csrf_matches,
    decode_token,
    hash_refresh_token,
    new_csrf_token,
    new_recovery_codes,
    new_refresh_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.schemas.auth import (
    AuthProvidersOut,
    LoginIn,
    LoginOut,
    RegisterIn,
    SessionOut,
    TokenOut,
    TwoFADisableIn,
    TwoFAEnableIn,
    TwoFAEnableOut,
    TwoFALoginIn,
    TwoFASetupOut,
    UserOut,
)
from app.schemas.common import Message
from app.services.users import create_user, plan_code_for

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def user_out(db: DB, user: User) -> UserOut:
    from sqlalchemy import inspect as sa_inspect

    if "twofa" in sa_inspect(user).unloaded:
        await db.refresh(user, ["twofa"])
    out = UserOut.model_validate(user)
    out.plan = await plan_code_for(db, user.id)
    return out


def _set_auth_cookies(response: Response, refresh_raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, refresh_raw, httponly=True, secure=s.cookie_secure, samesite="lax",
        max_age=s.jwt_refresh_ttl_days * 86400, path="/api/auth", domain=s.cookie_domain,
    )
    response.set_cookie(
        CSRF_COOKIE, new_csrf_token(), httponly=False, secure=s.cookie_secure, samesite="lax",
        max_age=s.jwt_refresh_ttl_days * 86400, path="/", domain=s.cookie_domain,
    )


def _clear_auth_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth", domain=s.cookie_domain)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=s.cookie_domain)


async def issue_session(
    db: DB, user: User, request: Request, response: Response, *, mfa: bool, family_id: str | None = None
) -> tuple[TokenOut, Session]:
    s = get_settings()
    raw, hashed = new_refresh_token()
    sess = Session(
        user_id=user.id, refresh_token_hash=hashed, family_id=family_id or uuid.uuid4().hex,
        user_agent=(request.headers.get("user-agent") or "")[:400], ip=client_ip(request),
        expires_at=utcnow() + timedelta(days=s.jwt_refresh_ttl_days), last_used_at=utcnow(),
    )
    db.add(sess)
    await db.flush()
    user.last_login_at = utcnow()
    _set_auth_cookies(response, raw)
    token = TokenOut(
        access_token=create_access_token(user.id, user.role, sess.id, mfa),
        expires_in=s.jwt_access_ttl_minutes * 60,
        user=await user_out(db, user),
    )
    return token, sess


def _require_csrf(request: Request) -> None:
    if not csrf_matches(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")


@router.get("/providers", response_model=AuthProvidersOut)
async def providers() -> AuthProvidersOut:
    s = get_settings()
    return AuthProvidersOut(google=s.google_oauth_configured, demo_login=s.environment != "production")


@router.post("/register", response_model=TokenOut, status_code=201, dependencies=[Depends(auth_rate_limit)])
async def register(body: RegisterIn, request: Request, response: Response, db: DB) -> TokenOut:
    if not (body.accept_terms and body.accept_privacy):
        raise HTTPException(422, "You must accept the terms, risk disclosure and privacy notice")
    exists = (await db.execute(select(User.id).where(User.email == body.email.lower()))).scalar()
    if exists:
        raise HTTPException(409, "An account with this email already exists")
    user = await create_user(
        db, email=body.email, password=body.password, full_name=body.full_name, ip=client_ip(request),
        consents={"terms": True, "privacy": True, "data_processing": True, "marketing": body.marketing_opt_in},
    )
    token, _ = await issue_session(db, user, request, response, mfa=False)
    return token


@router.post("/login", response_model=LoginOut, dependencies=[Depends(auth_rate_limit)])
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> LoginOut:
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        await audit(db, "auth.login_failed", payload={"email": body.email.lower()}, ip=client_ip(request),
                    actor="system")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user.totp_enabled:
        challenge = create_token(user.id, TWOFA_CHALLENGE, timedelta(minutes=5))
        return LoginOut(requires_2fa=True, challenge_token=challenge)
    token, _ = await issue_session(db, user, request, response, mfa=False)
    await audit(db, "auth.login", user_id=user.id, payload={"mfa": False}, ip=client_ip(request))
    return LoginOut(token=token)


@router.post("/login/2fa", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
async def login_2fa(body: TwoFALoginIn, request: Request, response: Response, db: DB) -> TokenOut:
    try:
        payload = decode_token(body.challenge_token, TWOFA_CHALLENGE)
    except jwt.PyJWTError:
        raise HTTPException(401, "2FA challenge expired, please sign in again")
    user = await db.get(User, int(payload["sub"]))
    if user is None or user.twofa is None or not user.twofa.enabled:
        raise HTTPException(401, "Invalid challenge")
    secret = Vault.from_settings().decrypt(user.twofa.secret_enc, aad=f"user:{user.id}:totp")
    step = verify_totp(secret, body.code, user.twofa.last_used_step)
    if step is None:
        import hashlib

        code_hash = hashlib.sha256(body.code.strip().encode()).hexdigest()
        if code_hash not in (user.twofa.recovery_codes_hash or []):
            raise HTTPException(401, "Invalid 2FA code")
        user.twofa.recovery_codes_hash = [h for h in user.twofa.recovery_codes_hash if h != code_hash]
        await audit(db, "auth.recovery_code_used", user_id=user.id)
    else:
        user.twofa.last_used_step = step
    token, _ = await issue_session(db, user, request, response, mfa=True)
    await audit(db, "auth.login", user_id=user.id, payload={"mfa": True}, ip=client_ip(request))
    return token


@router.post("/demo", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
async def demo_login(request: Request, response: Response, db: DB) -> TokenOut:
    """One-click login as the seeded demo user (disabled in production)."""
    s = get_settings()
    if s.environment == "production":
        raise HTTPException(404, "Not found")
    user = (await db.execute(select(User).where(User.email == s.demo_user_email))).scalar_one_or_none()
    if user is None:
        user = await create_user(
            db, email=s.demo_user_email, password=s.demo_user_password.get_secret_value(),
            full_name="Demo Trader", consents={"terms": True, "privacy": True, "data_processing": True},
        )
    token, _ = await issue_session(db, user, request, response, mfa=False)
    return token


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response, db: DB) -> TokenOut:
    _require_csrf(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(401, "No session")
    sess = (
        await db.execute(select(Session).where(Session.refresh_token_hash == hash_refresh_token(raw)))
    ).scalar_one_or_none()
    if sess is None:
        _clear_auth_cookies(response)
        raise HTTPException(401, "Invalid session")
    if sess.revoked_at is not None:
        # Refresh-token reuse => likely theft. Kill the whole family.
        await db.execute(
            update(Session).where(Session.family_id == sess.family_id, Session.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await audit(db, "auth.refresh_reuse_detected", user_id=sess.user_id, ip=client_ip(request),
                    actor="system", payload={"family": sess.family_id})
        await db.commit()
        _clear_auth_cookies(response)
        raise HTTPException(401, "Session revoked")
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires < utcnow():
        raise HTTPException(401, "Session expired")
    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "User inactive")
    # mfa claim survives rotation only if the original login was 2FA verified
    token, new_sess = await issue_session(db, user, request, response, mfa=user.totp_enabled,
                                          family_id=sess.family_id)
    sess.revoked_at = utcnow()
    sess.replaced_by_id = new_sess.id
    return token


@router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response, db: DB) -> Message:
    _require_csrf(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        sess = (
            await db.execute(select(Session).where(Session.refresh_token_hash == hash_refresh_token(raw)))
        ).scalar_one_or_none()
        if sess and sess.revoked_at is None:
            sess.revoked_at = utcnow()
            await audit(db, "auth.logout", user_id=sess.user_id)
    _clear_auth_cookies(response)
    return Message(message="Signed out")


# ---- Google OAuth ---------------------------------------------------------------------

@router.get("/google/start")
async def google_start() -> dict[str, str]:
    s = get_settings()
    if not s.google_oauth_configured:
        raise HTTPException(501, "Google sign-in is not configured (set GOOGLE_CLIENT_ID/SECRET)")
    state = secrets.token_urlsafe(24)
    await get_kv().set(f"oauth:google:{state}", "1", ttl=600)
    params = {
        "client_id": s.google_client_id, "redirect_uri": s.google_redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "access_type": "online", "prompt": "select_account",
    }
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}


@router.get("/google/callback")
async def google_callback(code: str, state: str, request: Request, db: DB) -> RedirectResponse:
    s = get_settings()
    kv = get_kv()
    if not s.google_oauth_configured or await kv.get(f"oauth:google:{state}") is None:
        raise HTTPException(400, "Invalid OAuth state")
    await kv.delete(f"oauth:google:{state}")
    assert s.google_client_secret is not None
    async with httpx.AsyncClient(timeout=10) as client:
        tok = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": s.google_client_id,
            "client_secret": s.google_client_secret.get_secret_value(),
            "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code",
        })
        if tok.status_code != 200:
            raise HTTPException(400, "Google token exchange failed")
        info = await client.get("https://openidconnect.googleapis.com/v1/userinfo",
                                headers={"Authorization": f"Bearer {tok.json()['access_token']}"})
    profile = info.json()
    if not profile.get("email_verified"):
        raise HTTPException(400, "Google account email is not verified")
    user = (await db.execute(select(User).where(User.google_sub == profile["sub"]))).scalar_one_or_none()
    if user is None:
        user = (await db.execute(select(User).where(User.email == profile["email"].lower()))).scalar_one_or_none()
        if user is not None:
            user.google_sub = profile["sub"]
            user.email_verified = True
        else:
            user = await create_user(
                db, email=profile["email"], password=None, full_name=profile.get("name", ""),
                google_sub=profile["sub"], avatar_url=profile.get("picture"), ip=client_ip(request),
                consents={"terms": True, "privacy": True, "data_processing": True},
            )
    redirect = RedirectResponse(f"{s.web_base_url}/auth/callback", status_code=302)
    if user.totp_enabled:
        challenge = create_token(user.id, TWOFA_CHALLENGE, timedelta(minutes=5))
        return RedirectResponse(f"{s.web_base_url}/login?challenge={challenge}", status_code=302)
    await issue_session(db, user, request, redirect, mfa=False)
    await audit(db, "auth.login", user_id=user.id, payload={"method": "google"}, ip=client_ip(request))
    return redirect


# ---- TOTP 2FA ---------------------------------------------------------------------------

@router.post("/2fa/setup", response_model=TwoFASetupOut)
async def twofa_setup(user: CurrentUser, db: DB) -> TwoFASetupOut:
    if user.totp_enabled:
        raise HTTPException(409, "2FA already enabled")
    secret = new_totp_secret()
    enc = Vault.from_settings().encrypt(secret, aad=f"user:{user.id}:totp")
    if user.twofa is None:
        db.add(UserTwoFA(user_id=user.id, secret_enc=enc, enabled=False))
    else:
        user.twofa.secret_enc = enc
    await db.flush()
    return TwoFASetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/2fa/enable", response_model=TwoFAEnableOut)
async def twofa_enable(body: TwoFAEnableIn, user: CurrentUser, db: DB) -> TwoFAEnableOut:
    await db.refresh(user, ["twofa"])
    if user.twofa is None:
        raise HTTPException(400, "Call /2fa/setup first")
    secret = Vault.from_settings().decrypt(user.twofa.secret_enc, aad=f"user:{user.id}:totp")
    step = verify_totp(secret, body.code)
    if step is None:
        raise HTTPException(400, "Invalid code, check your authenticator app clock")
    codes, hashes = new_recovery_codes()
    user.twofa.enabled = True
    user.twofa.confirmed_at = utcnow()
    user.twofa.last_used_step = step
    user.twofa.recovery_codes_hash = hashes
    await audit(db, "auth.2fa_enabled", user_id=user.id)
    return TwoFAEnableOut(enabled=True, recovery_codes=codes)


@router.post("/2fa/disable", response_model=Message)
async def twofa_disable(body: TwoFADisableIn, user: CurrentUser, db: DB) -> Message:
    if not user.totp_enabled or user.twofa is None:
        raise HTTPException(400, "2FA is not enabled")
    secret = Vault.from_settings().decrypt(user.twofa.secret_enc, aad=f"user:{user.id}:totp")
    if verify_totp(secret, body.code, user.twofa.last_used_step) is None:
        raise HTTPException(400, "Invalid code")
    await db.delete(user.twofa)
    await audit(db, "auth.2fa_disabled", user_id=user.id)
    return Message(message="Two-factor authentication disabled")


# ---- sessions ------------------------------------------------------------------------------

@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(user: CurrentUser, db: DB, request: Request) -> list[SessionOut]:
    rows = (
        await db.execute(
            select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .order_by(Session.created_at.desc())
        )
    ).scalars()
    raw = request.cookies.get(REFRESH_COOKIE)
    cur = hash_refresh_token(raw) if raw else None
    out = []
    for r in rows:
        item = SessionOut.model_validate(r)
        item.current = r.refresh_token_hash == cur
        out.append(item)
    return out


@router.delete("/sessions/{session_id}", response_model=Message)
async def revoke_session(session_id: int, user: CurrentUser, db: DB) -> Message:
    sess = await db.get(Session, session_id)
    if sess is None or sess.user_id != user.id:
        raise HTTPException(404, "Session not found")
    sess.revoked_at = utcnow()
    await audit(db, "auth.session_revoked", user_id=user.id, entity_type="session", entity_id=session_id)
    return Message(message="Session revoked")
