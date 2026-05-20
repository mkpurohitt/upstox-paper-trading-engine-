import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TokenStore:
    def __init__(self) -> None:
        self.path = Path(__file__).resolve().parents[3] / ".local" / "upstox_tokens.json"

    def save(self, mode: str, token_payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.load()
        payload[mode] = {
            "provider": "upstox",
            "mode": mode,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "token_payload": token_payload,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def access_token(self, mode: str = "live") -> str:
        payload = self.load().get(mode, {}).get("token_payload", {})
        return payload.get("access_token", "")

    def clear(self, mode: str | None = None) -> None:
        if not self.path.exists():
            return
        if mode is None:
            self.path.unlink()
            return
        payload = self.load()
        payload.pop(mode, None)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def status(self, mode: str = "live") -> dict[str, Any]:
        saved = self.load().get(mode, {})
        token_payload = saved.get("token_payload", {})
        return {
            "saved": bool(token_payload.get("access_token")),
            "received_at": saved.get("received_at"),
            "mode": mode,
            "token_type": token_payload.get("token_type"),
            "expires_in": token_payload.get("expires_in"),
        }


token_store = TokenStore()
