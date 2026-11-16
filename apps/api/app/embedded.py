"""Background services hosted inside the API process when EMBEDDED_WORKERS=true.

Each later phase registers its long-running loops here (tick streamer, strategy
runner manager, schedulers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.runtime import Runtime


async def start(rt: Runtime) -> None:
    return None
