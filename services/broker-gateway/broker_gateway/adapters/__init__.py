"""Broker adapter registry."""

from __future__ import annotations

from broker_gateway.adapters.aliceblue import AliceBlueAdapter
from broker_gateway.adapters.angel import AngelAdapter
from broker_gateway.adapters.dhan import DhanAdapter
from broker_gateway.adapters.fivepaisa import FivePaisaAdapter
from broker_gateway.adapters.fyers import FyersAdapter
from broker_gateway.adapters.icici import IciciBreezeAdapter
from broker_gateway.adapters.kotak import KotakAdapter
from broker_gateway.adapters.shoonya import ShoonyaAdapter
from broker_gateway.adapters.upstox import UpstoxAdapter
from broker_gateway.adapters.zerodha import ZerodhaAdapter
from broker_gateway.base import BrokerAdapter

ADAPTERS: dict[str, type[BrokerAdapter]] = {
    a.name: a
    for a in (UpstoxAdapter, ZerodhaAdapter, AngelAdapter, DhanAdapter, FyersAdapter, KotakAdapter, FivePaisaAdapter,
              IciciBreezeAdapter, AliceBlueAdapter, ShoonyaAdapter)
}


def adapter_class(broker: str) -> type[BrokerAdapter]:
    try:
        return ADAPTERS[broker]
    except KeyError as exc:
        raise KeyError(f"unknown broker {broker!r}") from exc


def catalog() -> list[dict[str, object]]:
    return [
        {"name": a.name, "display_name": a.display_name, "auth_type": a.auth_type, "docs_url": a.docs_url,
         "credential_fields": [f.model_dump() for f in a.credential_fields], "rate_limit_per_sec": a.rate_limit_per_sec}
        for a in ADAPTERS.values()
    ]
