from datetime import datetime
from typing import Any

from app.core.time import now_ist
from app.models.schemas import MarketTick


def normalize_quote_response(payload: dict[str, Any]) -> list[MarketTick]:
    ticks: list[MarketTick] = []
    for response_key, item in payload.get("data", {}).items():
        instrument_key = item.get("instrument_token") or item.get("instrument_key") or response_key.replace(":", "|", 1)
        if not instrument_key:
            continue
        ticks.append(
            MarketTick(
                instrument_key=instrument_key,
                timestamp=now_ist(),
                ltp=float(item.get("last_price") or 0),
                close=item.get("ohlc", {}).get("close"),
                bid=_first_depth_price(item, "buy"),
                ask=_first_depth_price(item, "sell"),
                volume=item.get("volume"),
                depth=item.get("depth", {}),
                raw=item,
            )
        )
    return ticks


def normalize_ws_feed(payload: dict[str, Any]) -> list[MarketTick]:
    current_ts = payload.get("currentTs")
    timestamp = datetime.fromtimestamp(int(current_ts) / 1000).astimezone() if current_ts else now_ist()
    ticks: list[MarketTick] = []
    for instrument_key, feed in payload.get("feeds", {}).items():
        market = feed.get("fullFeed", {}).get("marketFF") or feed.get("ltpc") or {}
        ltpc = market.get("ltpc", market)
        ticks.append(
            MarketTick(
                instrument_key=instrument_key,
                timestamp=timestamp,
                ltp=float(ltpc.get("ltp") or 0),
                close=ltpc.get("cp"),
                bid=_first_ws_depth_price(market, "bidP"),
                ask=_first_ws_depth_price(market, "askP"),
                volume=int(market.get("vtt") or 0) if market.get("vtt") else None,
                greeks=market.get("optionGreeks", {}),
                depth=market.get("marketLevel", {}),
                raw=feed,
            )
        )
    return ticks


def _first_depth_price(item: dict[str, Any], side: str) -> float | None:
    levels = item.get("depth", {}).get(side) or []
    return levels[0].get("price") if levels else None


def _first_ws_depth_price(item: dict[str, Any], field: str) -> float | None:
    levels = item.get("marketLevel", {}).get("bidAskQuote") or []
    return levels[0].get(field) if levels else None
