import gzip
import json
import shutil
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings


COMPLETE_JSON_GZ_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
COMPLETE_CSV_GZ_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"


class InstrumentMasterService:
    def __init__(self, settings: Settings) -> None:
        root = Path(__file__).resolve().parents[3]
        self.directory = settings.instruments_dir
        if not self.directory.is_absolute():
            self.directory = root / self.directory
        self.json_gz_path = self.directory / "complete.json.gz"
        self.json_path = self.directory / "complete.json"
        self.csv_gz_path = self.directory / "complete.csv.gz"
        self.csv_path = self.directory / "complete.csv"

    async def refresh(self) -> dict[str, str]:
        self.directory.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120) as client:
            await self._download(client, COMPLETE_JSON_GZ_URL, self.json_gz_path)
            await self._download(client, COMPLETE_CSV_GZ_URL, self.csv_gz_path)
        self._gunzip(self.json_gz_path, self.json_path)
        self._gunzip(self.csv_gz_path, self.csv_path)
        return self.status()

    def status(self) -> dict[str, str]:
        return {
            "directory": str(self.directory),
            "json": str(self.json_path),
            "csv": str(self.csv_path),
            "json_exists": str(self.json_path.exists()),
            "csv_exists": str(self.csv_path.exists()),
        }

    def search(self, query: str, segment: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        query = query.strip().upper()
        if not query or not self.json_path.exists():
            return []
        results: list[dict[str, Any]] = []
        with self.json_path.open("r", encoding="utf-8") as file:
            instruments = json.load(file)
        for item in instruments:
            if segment and item.get("segment") != segment:
                continue
            haystack = " ".join(
                str(item.get(field, ""))
                for field in ("instrument_key", "trading_symbol", "name", "short_name", "segment", "exchange")
            ).upper()
            if query in haystack:
                results.append(item)
                if len(results) >= limit:
                    break
        return results

    async def _download(self, client: httpx.AsyncClient, url: str, destination: Path) -> None:
        response = await client.get(url)
        response.raise_for_status()
        destination.write_bytes(response.content)

    def _gunzip(self, source: Path, destination: Path) -> None:
        with gzip.open(source, "rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst)
