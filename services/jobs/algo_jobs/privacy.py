"""Daily DPDP erasure of accounts whose deletion grace period has passed."""

from __future__ import annotations

from typing import Any

from algo_common.logging import get_logger
from algo_db.privacy import purge_due
from algo_db.session import session_scope
from algo_jobs.registry import cron, job

log = get_logger("jobs.privacy")


@job("purge_deleted_accounts")
async def purge_deleted_accounts(ctx: dict[str, Any] | None = None) -> dict[str, int]:
    async with session_scope() as db:
        n = await purge_due(db)
    log.info("privacy.purged_accounts", count=n)
    return {"purged": n}


cron("purge_deleted_accounts", hour={2}, minute={17})
