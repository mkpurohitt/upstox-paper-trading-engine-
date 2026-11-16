from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from algo_db.audit import audit
from app.core.deps import DB, CurrentUser
from app.routes.auth import user_out
from app.schemas.auth import UserOut

router = APIRouter(prefix="/api/me", tags=["me"])


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20, pattern=r"^\+?[0-9 ]{7,20}$")
    theme: str | None = Field(default=None, pattern="^(dark|light|system)$")
    notification_prefs: dict[str, Any] | None = None


@router.get("", response_model=UserOut)
async def me(user: CurrentUser, db: DB) -> UserOut:
    return await user_out(db, user)


@router.patch("", response_model=UserOut)
async def update_me(body: UserPatch, user: CurrentUser, db: DB) -> UserOut:
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(user, k, v)
    await audit(db, "user.update", user_id=user.id, payload={"fields": sorted(changes)})
    await db.flush()
    return await user_out(db, user)
