import asyncio
import logging

from homeassistant.components.climate.const import HVACMode

from .const import CONF_IP_ADDRESS, DOMAIN
from .drying_store import DryingStore
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

async def _async_update_listener(hass, entry) -> None:
    """Reload the entry so changed options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass, entry):
    await _async_migrate_legacy_unique_id(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"config": entry.data}
    await hass.config_entries.async_forward_entry_setups(
        entry, ["climate", "switch", "sensor", "select"]
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
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


async def async_remove_entry(hass, entry):
    """Power off a unit left in a post-off drying cycle, then drop the record."""
    from .climate import LocalDaikin  # deferred: climate imports are heavy

    store = DryingStore(hass, entry.entry_id)
    try:
        if await store.async_load() is not None:
            unit = LocalDaikin(entry.data[CONF_IP_ADDRESS])
            await hass.async_add_executor_job(unit.update)
            if unit._hvac_mode == HVACMode.FAN_ONLY:
                await hass.async_add_executor_job(unit._update_state, False)
    except Exception:  # noqa: BLE001 - removal must not fail
        _LOGGER.warning(
            "Could not power off Local Daikin after removal; "
            "a drying cycle may still be running",
            exc_info=True,
        )
    finally:
        await store.async_remove()
