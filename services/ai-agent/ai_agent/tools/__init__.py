"""Agent tools. Importing the modules registers them."""

from __future__ import annotations

_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    from ai_agent.tools import analysis, market, portfolio, strategy  # noqa: F401

    _loaded = True
