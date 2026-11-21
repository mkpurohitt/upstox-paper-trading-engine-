"""Central, typed configuration loaded from environment variables (and `.env`).

Every secret is a `SecretStr` so it never leaks into logs or reprs. Missing
provider credentials are *not* errors: the platform falls back to mock
providers so the whole product works offline (see `DATA_MODE`).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-0123456789abcdef"
# 32 zero-ish bytes, base64 encoded. Only accepted outside production.
_DEV_VAULT_KEY = base64.b64encode(b"dev-only-vault-key-32-bytes!!!!!").decode()


def _project_root() -> Path:
    """The monorepo root (the directory holding ``uv.lock``), or the working directory outside a checkout."""
    cwd = Path.cwd().resolve()
    for d in (cwd, *cwd.parents):
        if (d / "uv.lock").is_file():
            return d
    return cwd


def _resolve_sqlite_url(url: str) -> str:
    """Make a relative SQLite path independent of the working directory.

    ``sqlite+aiosqlite:///./var/algo.db`` resolves against the repository root, so the API, the seed script and
    Alembic share one database whether they run from the root or from ``apps/api`` (on Windows and POSIX alike).
    The parent directory is created. In-memory URLs and absolute paths are returned unchanged.
    """
    prefix, sep, path = url.partition(":///")
    if not sep or not prefix.startswith("sqlite") or not path or ":memory:" in path or path.startswith("file:"):
        return url
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)
        query = "?" + query
    p = Path(path)
    if p.is_absolute() or path.startswith("/"):
        return url
    resolved = (_project_root() / p).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}:///{resolved.as_posix()}{query}"


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `KEY=` in .env means "not set" (use the default), not an empty string
        extra="ignore",
        case_sensitive=False,
    )

    # ---- application -------------------------------------------------------
    app_name: str = "AlgoDesk"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    data_mode: Literal["mock", "live"] = "mock"
    embedded_workers: bool = Field(
        default=True,
        description="Run tick streamer, live strategy runners and background jobs inside the API "
        "process. Set false when the dedicated worker containers are running.",
    )
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    data_region: str = "ap-south-1"

    # ---- storage ------------------------------------------------------------
    # Local default: a SQLite file under ./var (no Docker needed). Compose and production set a PostgreSQL URL.
    database_url: str = "sqlite+aiosqlite:///./var/algo.db"
    db_echo: bool = False
    db_pool_size: int = 10
    pgvector_enabled: bool = False
    redis_url: str | None = None

    # ---- auth ---------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str = "http://localhost:3000/api/auth/google/callback"
    demo_user_email: str = "demo@algodesk.in"
    demo_user_password: SecretStr = SecretStr("demo12345")

    # ---- encryption vault (AES-256-GCM) ---------------------------------------
    vault_master_key: SecretStr = SecretStr(_DEV_VAULT_KEY)
    vault_key_id: str = "v1"
    vault_previous_keys: SecretStr | None = Field(
        default=None, description="Comma separated `keyid:base64key` pairs kept for decryption during rotation"
    )

    # ---- market data --------------------------------------------------------
    upstox_api_key: str | None = None
    upstox_api_secret: SecretStr | None = None
    upstox_redirect_uri: str = "http://localhost:8000/api/brokers/upstox/callback"
    upstox_analytics_token: SecretStr | None = None
    upstox_base_url: str = "https://api.upstox.com"
    upstox_instruments_url: str = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
    upstox_rate_limit_per_sec: int = 25
    nse_mcp_url: str | None = None
    nse_mcp_transport: Literal["streamable_http", "sse"] = "streamable_http"
    nse_mcp_api_key: SecretStr | None = None
    tick_interval_ms: int = 1000
    mock_seed: int = 42

    # ---- brokers & risk -------------------------------------------------------
    default_broker: str = "paper"
    order_rate_limit_per_sec: int = Field(default=8, description="Per exchange per client; SEBI retail threshold is 10/s")
    paper_slippage_bps: float = 5.0
    paper_starting_capital: float = 1_000_000.0
    # Paper orders respect exchange hours: outside them they queue as after-market orders (AMO) and fill at the open.
    paper_market_hours: bool = True
    global_kill_switch: bool = False
    algo_id_prefix: str = "ALGO-PENDING"
    egress_static_ip: str | None = None
    broker_http_timeout_s: float = 10.0

    # ---- AI -----------------------------------------------------------------
    llm_primary_provider: Literal["openai_compat", "anthropic", "ollama", "mock"] = "openai_compat"
    llm_primary_model: str = "gpt-6-luna"
    llm_primary_base_url: str | None = None
    llm_primary_api_key: SecretStr | None = None
    llm_cheap_model: str | None = None
    llm_strong_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model_strong: str = "claude-opus-5-5"
    anthropic_model_cheap: str = "claude-haiku-5-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    embedding_provider: Literal["hashing", "openai_compat", "ollama"] = "hashing"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    advice_enabled: bool = False
    llm_max_tool_steps: int = 6
    llm_request_timeout_s: float = 60.0
    llm_fallbacks: str = "anthropic,ollama"  # tried in order after the primary; the rule-based mock is always last
    ollama_enabled: bool = False
    llm_mock_fallback: bool = True
    llm_pricing_json: str = "{}"  # {"model": [usd_per_1m_in, usd_per_1m_out]} for cost tracking
    rag_top_k: int = 4

    # ---- news -----------------------------------------------------------------
    news_rss_feeds: str = (
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms,"
        "https://www.livemint.com/rss/markets,"
        "https://www.moneycontrol.com/rss/marketreports.xml"
    )
    news_refresh_minutes: int = 15

    # ---- notifications -------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "alerts@algodesk.in"
    telegram_bot_token: SecretStr | None = None
    whatsapp_webhook_url: str | None = None

    # ---- billing (Razorpay test mode) ----------------------------------------
    razorpay_key_id: str | None = None
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None

    # ---- observability ----------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    sentry_dsn: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "algo-api"

    # ---- request limits ---------------------------------------------------------
    api_rate_limit_per_min: int = 600
    auth_rate_limit_per_min: int = 30

    @field_validator("redis_url", mode="before")
    @classmethod
    def _redis_off(cls, v: object) -> object:
        # "none"/"off"/"memory" force the in-process bus/cache even if a .env file sets a Redis URL.
        if isinstance(v, str) and v.strip().lower() in {"", "none", "off", "memory", "false"}:
            return None
        return v

    @model_validator(mode="after")
    def _normalise_database_url(self) -> Settings:
        if self.database_url.startswith("sqlite"):
            self.database_url = _resolve_sqlite_url(self.database_url)
        return self

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> Settings:
        if self.environment == "production":
            if self.database_url.startswith("sqlite"):
                raise ValueError("DATABASE_URL must point to PostgreSQL in production")
            if self.jwt_secret.get_secret_value() == _DEV_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set in production")
            if self.vault_master_key.get_secret_value() == _DEV_VAULT_KEY:
                raise ValueError("VAULT_MASTER_KEY must be set in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
        return self

    # ---- derived helpers -------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return _split(self.cors_origins)

    @property
    def news_feed_list(self) -> list[str]:
        return _split(self.news_rss_feeds)

    @property
    def is_live_data(self) -> bool:
        return self.data_mode == "live"

    @property
    def upstox_configured(self) -> bool:
        return self.upstox_analytics_token is not None and bool(self.upstox_analytics_token.get_secret_value())

    @property
    def llm_configured(self) -> bool:
        if self.llm_primary_provider == "mock":
            return False
        if self.llm_primary_provider == "anthropic":
            return self.anthropic_api_key is not None
        if self.llm_primary_provider == "ollama":
            return True
        return self.llm_primary_api_key is not None and self.llm_primary_base_url is not None

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
