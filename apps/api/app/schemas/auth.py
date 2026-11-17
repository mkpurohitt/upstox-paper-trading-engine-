from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORM


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=200)
    accept_terms: bool = Field(description="Terms of use + risk disclosure (required)")
    accept_privacy: bool = Field(description="Privacy notice / DPDP consent (required)")
    marketing_opt_in: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TwoFALoginIn(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=20)


class UserOut(ORM):
    id: int
    email: str
    full_name: str
    role: str
    phone: str | None = None
    avatar_url: str | None = None
    kyc_status: str
    theme: str
    email_verified: bool
    totp_enabled: bool
    kill_switch: bool
    notification_prefs: dict[str, Any] = {}
    created_at: datetime
    plan: str = "free"
    pan_last4: str | None = None
    deletion_requested_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class LoginOut(BaseModel):
    requires_2fa: bool = False
    challenge_token: str | None = None
    token: TokenOut | None = None


class TwoFASetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFAEnableIn(BaseModel):
    code: str


class TwoFAEnableOut(BaseModel):
    enabled: bool
    recovery_codes: list[str]


class TwoFADisableIn(BaseModel):
    code: str


class AuthProvidersOut(BaseModel):
    password: bool = True
    google: bool
    demo_login: bool


class SessionOut(ORM):
    id: int
    user_agent: str | None
    ip: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    current: bool = False
