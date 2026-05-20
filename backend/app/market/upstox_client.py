from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.data.token_store import token_store


class UpstoxClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _headers(self, token: str | None = None, mode: str = "live") -> dict[str, str]:
        access_token = token or token_store.access_token(mode) or self.settings.live_token
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

    def login_url(self, state: str | None = None, mode: str = "live") -> str:
        client_id = self.settings.live_client_id if mode == "live" else self.settings.sandbox_client_id
        redirect_uri = self.settings.upstox_redirect_uri if mode == "live" else self.settings.upstox_sandbox_redirect_uri
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        }
        if state:
            params["state"] = state
        return f"{self.settings.upstox_base_url}/v2/login/authorization/dialog?{httpx.QueryParams(params)}"

    async def exchange_code(self, code: str, mode: str = "live") -> dict[str, Any]:
        client_id = self.settings.live_client_id if mode == "live" else self.settings.sandbox_client_id
        client_secret = self.settings.live_client_secret if mode == "live" else self.settings.sandbox_client_secret
        redirect_uri = self.settings.upstox_redirect_uri if mode == "live" else self.settings.upstox_sandbox_redirect_uri
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.settings.upstox_base_url}/v2/login/authorization/token",
                headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                data=data,
            )
            response.raise_for_status()
            return response.json()

    async def get_market_authorize_url_v3(self) -> str:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(
                f"{self.settings.upstox_base_url}/v3/feed/market-data-feed/authorize",
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()["data"]["authorized_redirect_uri"]

    async def full_market_quote(self, instrument_keys: list[str]) -> dict[str, Any]:
        params = {"instrument_key": ",".join(instrument_keys)}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.upstox_base_url}/v2/market-quote/quotes",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def option_contracts(self, instrument_key: str, expiry_date: str | None = None) -> dict[str, Any]:
        params: dict[str, str] = {"instrument_key": instrument_key}
        if expiry_date:
            params["expiry_date"] = expiry_date
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.upstox_base_url}/v2/option/contract",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def option_chain(self, instrument_key: str, expiry_date: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.upstox_base_url}/v2/option/chain",
                params={"instrument_key": instrument_key, "expiry_date": expiry_date},
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def historical_candles(
        self,
        instrument_key: str,
        unit: str,
        interval: str,
        to_date: str,
        from_date: str | None = None,
    ) -> dict[str, Any]:
        encoded_instrument = quote(instrument_key, safe="")
        path = f"/v3/historical-candle/{encoded_instrument}/{unit}/{interval}/{to_date}"
        if from_date:
            path += f"/{from_date}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.settings.upstox_base_url}{path}", headers=self._headers())
            response.raise_for_status()
            return response.json()
