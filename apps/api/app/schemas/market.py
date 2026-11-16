from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MoverRow(BaseModel):
    symbol: str
    name: str | None = None
    ltp: float
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    value_cr: float | None = None
    oi: float | None = None
    oi_change_pct: float | None = None
    buildup: str | None = None


class SectorStock(BaseModel):
    symbol: str
    name: str | None = None
    ltp: float
    change_pct: float | None = None
    mcap_cr: float


class SectorTile(BaseModel):
    sector: str
    change_pct: float
    mcap_cr: float
    stocks: list[SectorStock]


class Breadth(BaseModel):
    advances: int
    declines: int
    unchanged: int
    universe: int
    nse: dict[str, Any] = {}


class OverviewOut(BaseModel):
    ts: str
    indices: list[MoverRow]
    sector_indices: list[MoverRow]
    sectors: list[SectorTile]
    breadth: Breadth
    top_gainers: list[MoverRow]
    top_losers: list[MoverRow]
    most_active: list[MoverRow]
    oi_gainers: list[MoverRow]
    oi_losers: list[MoverRow]
    fii_dii: dict[str, Any]


class ProviderInfo(BaseModel):
    name: str
    live: bool
    data_mode: str


class McpToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
