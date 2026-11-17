"""Fresh SQLite DB + in-memory bus/KV for broker-gateway tests."""

from __future__ import annotations

import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="bg-test-")
os.environ.update({"DATABASE_URL": f"sqlite+aiosqlite:///{_tmp}/bg.db", "REDIS_URL": "", "DATA_MODE": "mock",
                   "ENVIRONMENT": "test", "LOG_LEVEL": "WARNING", "LOG_JSON": "false"})

from algo_common.settings import reset_settings_cache  # noqa: E402

reset_settings_cache()


@pytest.fixture()
async def db():
    from algo_common.bus import InMemoryBus, set_bus
    from algo_common.kv import MemoryKV, set_kv
    from algo_db.session import configure_engine, create_all, dispose_engine, get_sessionmaker

    set_bus(InMemoryBus())
    set_kv(MemoryKV())
    path = tempfile.mktemp(suffix=".db", dir=_tmp)
    configure_engine(f"sqlite+aiosqlite:///{path}")
    await create_all()
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        await session.close()
        await dispose_engine()


@pytest.fixture()
async def user(db):
    from algo_db.models import RiskLimit, User

    u = User(email="t@example.com", full_name="T", twofa=None)
    db.add(u)
    await db.flush()
    db.add(RiskLimit(user_id=u.id))
    await db.commit()
    return u
