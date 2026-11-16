"""API test fixtures: fresh SQLite database + in-memory bus/KV per test session."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

_tmp = tempfile.mkdtemp(prefix="algo-test-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        # Set TEST_DATABASE_URL to run the suite against a migrated Postgres (CI does this).
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{_tmp}/test.db",
        "REDIS_URL": "",
        "DATA_MODE": "mock",
        "EMBEDDED_WORKERS": "true",
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
        "API_RATE_LIMIT_PER_MIN": "100000",
        "AUTH_RATE_LIMIT_PER_MIN": "100000",
        "LLM_PRIMARY_PROVIDER": "mock",
        "TICK_INTERVAL_MS": "200",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from algo_common.settings import reset_settings_cache  # noqa: E402

reset_settings_cache()


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def register(client: TestClient, email: str, password: str = "password123") -> dict:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Test", "accept_terms": True,
              "accept_privacy": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    import uuid

    tok = register(client, f"user-{uuid.uuid4().hex[:8]}@example.com")
    return {"Authorization": f"Bearer {tok['access_token']}"}
