"""Persistence for a running post-off drying cycle."""

from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN


class DryingStore:
    """Keeps the drying deadline across Home Assistant restarts."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store = Store(hass, 1, f"{DOMAIN}.post_off_drying.{entry_id}")

    async def async_load(self) -> float | None:
        data = await self._store.async_load()
        deadline = data.get("deadline") if isinstance(data, dict) else None
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            return None
        return float(deadline)

    def save(self, deadline: float | None) -> None:
        """Blocks on the event loop: call from executor threads only."""
        coro = (
            self._store.async_remove()
            if deadline is None
            else self._store.async_save({"deadline": deadline})
        )
        asyncio.run_coroutine_threadsafe(coro, self._hass.loop).result(timeout=10)

    async def async_remove(self) -> None:
        await self._store.async_remove()
