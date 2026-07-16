import asyncio
import logging

from .const import DOMAIN
from .scanner import (
    DaikinConnectionError,
    async_get_device_info,
    uses_legacy_unique_id,
)

_LOGGER = logging.getLogger(__name__)


async def _async_migrate_legacy_unique_id(hass, entry):
    """Best-effort migration from a mutable IP identity to the adapter MAC."""
    if not uses_legacy_unique_id(entry.unique_id):
        return

    ip = entry.data.get("ip_address")
    if not ip:
        return

    try:
        device = await async_get_device_info(hass, ip)
    except DaikinConnectionError:
        _LOGGER.debug("Deferring Local Daikin identity migration for %s", ip)
        return
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unable to migrate Local Daikin identity for %s", ip)
        return

    existing = hass.config_entries.async_entry_for_domain_unique_id(
        DOMAIN, device.mac
    )
    if existing is not None and existing.entry_id != entry.entry_id:
        _LOGGER.error(
            "Cannot migrate Local Daikin %s to MAC %s because it is already used",
            ip,
            device.mac,
        )
        return
    hass.config_entries.async_update_entry(entry, unique_id=device.mac)


async def async_setup(hass, config):
    return True

async def async_setup_entry(hass, entry):
    await _async_migrate_legacy_unique_id(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"config": entry.data}
    await hass.config_entries.async_forward_entry_setups(
        entry, ["climate", "switch", "sensor", "select"]
    )
    return True

async def async_unload_entry(hass, entry):
    unload_ok = all(
        await asyncio.gather(*[
            hass.config_entries.async_forward_entry_unload(entry, platform)
            for platform in ("climate", "switch", "sensor", "select")
        ])
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
