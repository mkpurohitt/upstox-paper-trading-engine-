import asyncio
from datetime import date

import pytest

from algo_common.bus import InMemoryBus
from algo_common.crypto import Vault, VaultError, mask
from algo_common.kv import MemoryKV
from algo_common.logging import redact_processor
from algo_common.ratelimit import SlidingWindowLimiter
from algo_common.timeutils import monthly_expiry, upcoming_expiries

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="  # 32 bytes


def test_vault_roundtrip_and_aad_binding():
    v = Vault("v1", KEY)
    token = v.encrypt_json({"api_key": "k", "secret": "s"}, aad="user:1")
    assert token.startswith("v1:")
    assert v.decrypt_json(token, aad="user:1") == {"api_key": "k", "secret": "s"}
    with pytest.raises(VaultError):
        v.decrypt(token, aad="user:2")


def test_vault_rotation():
    old = Vault("v1", KEY)
    token = old.encrypt("hello")
    new_key = "ZmVkY2JhOTg3NjU0MzIxMGZlZGNiYTk4NzY1NDMyMTA="
    new = Vault("v2", new_key, previous={"v1": KEY})
    assert new.needs_rotation(token)
    rotated = new.rotate(token)
    assert rotated.startswith("v2:") and new.decrypt(rotated) == "hello"


def test_mask():
    assert mask("abcdefghij").endswith("ghij")
    assert "abc" not in mask("abcdefghij")


def test_redaction():
    out = redact_processor(None, "", {"event": "x", "api_key": "123", "nested": {"password": "p", "ok": 1}})
    assert out["api_key"] == "***"
    assert out["nested"]["password"] == "***" and out["nested"]["ok"] == 1


async def test_inmemory_bus_pattern_fanout():
    bus = InMemoryBus()
    received: list[tuple[str, dict]] = []

    async def consume():
        async for ch, msg in bus.subscribe("ticks:*"):
            received.append((ch, msg))
            if len(received) == 2:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await bus.publish("ticks:NSE:RELIANCE", {"ltp": 1})
    await bus.publish("orders:1", {"x": 1})
    await bus.publish("ticks:NSE:TCS", {"ltp": 2})
    await asyncio.wait_for(task, 1)
    assert [c for c, _ in received] == ["ticks:NSE:RELIANCE", "ticks:NSE:TCS"]


async def test_sliding_window_limiter():
    lim = SlidingWindowLimiter(3, 1.0, kv=MemoryKV())
    results = [(await lim.hit("u1"))[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_expiry_rules():
    # NSE monthly expiry is the last Tuesday of the month
    e = monthly_expiry(2026, 12, "NSE")
    assert e.weekday() == 1 and e.month == 12
    weekly = upcoming_expiries("NIFTY", date(2026, 11, 16), count=3)
    assert len(weekly) == 3 and all(d.weekday() in (0, 1) for d in weekly)
    monthly = upcoming_expiries("BANKNIFTY", date(2026, 11, 16), count=2)
    assert monthly[0].month == 11 and monthly[1].month == 12
