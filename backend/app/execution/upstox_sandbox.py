from typing import Any

import httpx

from app.core.config import Settings
from app.data.token_store import token_store
from app.models.schemas import Order


class UpstoxSandboxExecutionAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def place_order(self, order: Order) -> dict[str, Any]:
        if not self.settings.enable_order_submission:
            return {"status": "success", "data": {"order_ids": [f"sim_{order.id}"]}, "metadata": {"mode": "local_simulation"}}
        access_token = token_store.access_token("sandbox") or self.settings.sandbox_token
        if not access_token:
            raise RuntimeError("ENABLE_ORDER_SUBMISSION is true, but no saved sandbox access token or UPSTOX_SANDBOX_ACCESS_TOKEN is available.")
        payload = {
            "quantity": order.quantity,
            "product": order.product.value if hasattr(order.product, "value") else str(order.product),
            "validity": "DAY",
            "price": order.price,
            "tag": order.idempotency_key[:40],
            "instrument_token": order.instrument_key,
            "order_type": order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
            "transaction_type": order.side.value if hasattr(order.side, "value") else str(order.side),
            "disclosed_quantity": 0,
            "trigger_price": order.trigger_price,
            "is_amo": False,
            "slice": True,
            "market_protection": -1,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.settings.upstox_hft_base_url}/v3/order/place", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
