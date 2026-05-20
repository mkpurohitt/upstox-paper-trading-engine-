from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "upstox-paper-trading-platform"
    app_env: str = "local"
    mode: Literal["paper", "live"] = "paper"
    log_level: str = "INFO"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    database_url: str = "sqlite:///./paper.sqlite3"
    redis_url: str = "redis://localhost:6379/0"

    upstox_live_api_key: str = ""
    upstox_live_api_secret: str = ""
    upstox_client_id: str = ""
    upstox_client_secret: str = ""
    upstox_redirect_uri: str = "http://localhost:8000/broker/callback"
    upstox_access_token: str = ""
    upstox_extended_token: str = ""
    upstox_sandbox_api_key: str = ""
    upstox_sandbox_api_secret: str = ""
    upstox_sandbox_client_id: str = ""
    upstox_sandbox_client_secret: str = ""
    upstox_sandbox_redirect_uri: str = "http://localhost:8000/broker/sandbox/callback"
    upstox_sandbox_access_token: str = ""
    upstox_base_url: str = "https://api.upstox.com"
    upstox_hft_base_url: str = "https://api-hft.upstox.com"

    base_capital: float = 1_000_000
    default_currency: str = "INR"
    default_instruments: str = "NSE_INDEX|Nifty 50"
    download_instruments_on_start: bool = True
    instruments_dir: Path = Field(default=Path("data/instruments"))
    enable_live_quote_polling: bool = True
    enable_live_upstox_ws: bool = False
    enable_order_submission: bool = False

    risk_max_loss_per_day: float = 20_000
    risk_max_position_size: float = 100_000
    risk_max_order_value: float = 250_000
    risk_max_orders_per_minute: int = 20
    risk_max_trades_per_strategy: int = 100

    strategy_root: Path = Field(default=Path("../strategies/sample_strategies"))

    @property
    def live_token(self) -> str:
        return self._configured_token(self.upstox_access_token) or self._configured_token(self.upstox_extended_token)

    @property
    def sandbox_token(self) -> str:
        return self._configured_token(self.upstox_sandbox_access_token)

    @property
    def live_client_id(self) -> str:
        return self._configured_token(self.upstox_live_api_key) or self._configured_token(self.upstox_client_id)

    @property
    def live_client_secret(self) -> str:
        return self._configured_token(self.upstox_live_api_secret) or self._configured_token(self.upstox_client_secret)

    @property
    def sandbox_client_id(self) -> str:
        return self._configured_token(self.upstox_sandbox_api_key) or self._configured_token(self.upstox_sandbox_client_id)

    @property
    def sandbox_client_secret(self) -> str:
        return self._configured_token(self.upstox_sandbox_api_secret) or self._configured_token(self.upstox_sandbox_client_secret)

    @property
    def default_instrument_list(self) -> list[str]:
        return [item.strip() for item in self.default_instruments.split(",") if item.strip()]

    def _configured_token(self, value: str) -> str:
        value = value.strip()
        if not value or value.startswith("PASTE_"):
            return ""
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
