import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.time import now_ist
from app.data.repository import repo
from app.data.token_store import token_store
from app.market.upstox_client import UpstoxClient
from app.models.schemas import DashboardSummary, Signal
from app.services.container import services
from app.services.event_bus import event_bus

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "time": now_ist().isoformat()}


@router.get("/system/status")
async def system_status() -> dict[str, Any]:
    return {
        "time": now_ist().isoformat(),
        "warnings": services.startup_warnings,
        "live_quote": services.live_quote.status(),
        "instruments": services.instruments.status(),
        "tokens": {
            "live": token_store.status("live"),
            "sandbox_env_configured": bool(get_settings().sandbox_token),
        },
    }


@router.get("/auth/login")
async def auth_login(state: str | None = None, mode: str = "live") -> dict[str, str]:
    if mode == "sandbox":
        return {
            "mode": "sandbox",
            "login_url": "",
            "message": "Upstox sandbox tokens are generated in Developer Apps, not through OAuth login.",
            "sandbox_apps_url": "https://account.upstox.com/developer/apps",
        }
    return {"mode": "live", "login_url": UpstoxClient(get_settings()).login_url(state, "live")}


@router.get("/auth/login/redirect")
async def auth_login_redirect(state: str | None = None, mode: str = "live") -> RedirectResponse:
    if mode == "sandbox":
        return RedirectResponse("https://account.upstox.com/developer/apps")
    return RedirectResponse(UpstoxClient(get_settings()).login_url(state, "live"))


@router.get("/broker/connect")
async def broker_connect() -> dict[str, Any]:
    settings = get_settings()
    live_token = token_store.status("live")
    sandbox_token = token_store.status("sandbox")
    return {
        "provider_name": "upstox",
        "sandbox_enabled": bool(sandbox_token["saved"] or settings.sandbox_token),
        "live_token_configured": bool(live_token["saved"] or settings.live_token),
        "live_token": live_token,
        "sandbox_token": sandbox_token,
        "login_url": UpstoxClient(settings).login_url("paper-platform", "live"),
        "sandbox_apps_url": "https://account.upstox.com/developer/apps",
    }


@router.get("/broker/callback")
async def broker_callback(code: str, state: str | None = None) -> dict[str, Any]:
    token_payload = await UpstoxClient(get_settings()).exchange_code(code, "live")
    token_store.save("live", token_payload)
    return {"status": "saved", "mode": "live", "state": state, "token": token_store.status("live")}


@router.post("/broker/disconnect")
async def broker_disconnect(mode: str | None = None) -> dict[str, str]:
    token_store.clear(mode if mode in {"live", "sandbox"} else None)
    return {"status": f"saved Upstox token cleared for {mode or 'all modes'}"}


@router.get("/strategies")
async def list_strategies() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repo.strategies.values()]


@router.post("/strategies/run/{strategy_id}")
async def run_strategy(strategy_id: str) -> dict[str, Any]:
    run = await services.strategy_engine.start_strategy(strategy_id)
    return run.model_dump(mode="json")


@router.post("/strategies/run")
async def run_strategy_from_body(payload: dict[str, str]) -> dict[str, Any]:
    run = await services.strategy_engine.start_strategy(payload["strategy_id"])
    return run.model_dump(mode="json")


@router.post("/strategies/stop/{strategy_id}")
async def stop_strategy(strategy_id: str) -> dict[str, str]:
    await services.strategy_engine.stop_strategy(strategy_id)
    return {"status": "stopped"}


@router.post("/strategies/stop")
async def stop_strategy_from_body(payload: dict[str, str]) -> dict[str, str]:
    await services.strategy_engine.stop_strategy(payload["strategy_id"])
    return {"status": "stopped"}


@router.get("/signals")
async def signals() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repo.signals.values()]


@router.post("/signals")
async def create_signal(signal: Signal) -> dict[str, Any]:
    repo.signals[signal.id] = signal
    order = await services.oms.route_signal(signal)
    return {"signal": signal.model_dump(mode="json"), "order": order.model_dump(mode="json") if order else None}


@router.get("/orders")
async def orders() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repo.orders.values()]


@router.get("/positions")
async def positions() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repo.positions.values()]


@router.get("/pnl")
async def pnl() -> dict[str, float]:
    realized = sum(item.realized_pnl for item in repo.positions.values())
    unrealized = sum(item.unrealized_pnl for item in repo.positions.values())
    return {"realized": realized, "unrealized": unrealized, "mtm": realized + unrealized}


@router.get("/capital")
async def get_capital() -> dict[str, Any]:
    return repo.ensure_capital(get_settings().base_capital).model_dump(mode="json")


@router.put("/capital")
async def update_capital(payload: dict[str, float]) -> dict[str, Any]:
    capital = repo.ensure_capital(get_settings().base_capital)
    amount = payload.get("starting_capital", capital.starting_capital)
    capital.starting_capital = amount
    capital.current_capital = amount + sum(pos.mtm for pos in repo.positions.values())
    capital.available_margin = capital.current_capital
    capital.updated_at = now_ist()
    await event_bus.publish("pnl-updates", capital.model_dump(mode="json"))
    return capital.model_dump(mode="json")


@router.get("/rms/events")
async def rms_events() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repo.rms_events]


@router.get("/reconciliation")
async def reconciliation() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repo.reconciliation_events]


@router.post("/market/subscribe")
async def subscribe(payload: dict[str, list[str]]) -> dict[str, list[str]]:
    return {"subscriptions": await services.market_data.subscribe(payload.get("instrument_keys", []))}


@router.get("/market/instruments")
async def instruments() -> dict[str, Any]:
    return {
        "configured": sorted(services.market_data.subscriptions),
        "latest": [tick.model_dump(mode="json") for tick in repo.ticks.values()],
        "master": services.instruments.status(),
    }


@router.post("/market/instruments/refresh")
async def refresh_instruments() -> dict[str, str]:
    return await services.instruments.refresh()


@router.get("/market/instruments/search")
async def search_instruments(q: str, segment: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    return services.instruments.search(q, segment, limit)


@router.get("/market/option-chain")
async def option_chain(instrument_key: str, expiry_date: str) -> dict[str, Any]:
    return await UpstoxClient(get_settings()).option_chain(instrument_key, expiry_date)


@router.get("/market/greeks")
async def greeks() -> dict[str, Any]:
    return {key: tick.greeks for key, tick in repo.ticks.items()}


@router.get("/market/candles")
async def candles(instrument_key: str, unit: str = "minutes", interval: str = "1", to_date: str = "2026-05-19", from_date: str | None = None) -> dict[str, Any]:
    return await UpstoxClient(get_settings()).historical_candles(instrument_key, unit, interval, to_date, from_date)


@router.get("/dashboard/summary")
async def dashboard_summary() -> dict[str, Any]:
    capital = repo.ensure_capital(get_settings().base_capital)
    pnl_values = await pnl()
    return DashboardSummary(
        mode=get_settings().mode,
        capital=capital,
        positions=list(repo.positions.values()),
        open_orders=[order for order in repo.orders.values() if str(order.status) not in {"FILLED", "CANCELLED", "REJECTED"}],
        signals=list(repo.signals.values())[-25:],
        rms_events=list(repo.rms_events)[:25],
        reconciliation_events=list(repo.reconciliation_events)[:25],
        pnl=pnl_values,
    ).model_dump(mode="json")


@router.websocket("/ws/{channel}")
async def websocket_channel(websocket: WebSocket, channel: str) -> None:
    await websocket.accept()
    queue = event_bus.subscribe(channel)
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_json(message)
            except asyncio.TimeoutError:
                await websocket.send_json({"channel": channel, "payload": {"heartbeat": now_ist().isoformat()}})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        event_bus.unsubscribe(channel, queue)
