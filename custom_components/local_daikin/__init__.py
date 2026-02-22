import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass, config):
    _LOGGER.debug("local_daikin async_setup called")
    return True

async def async_setup_entry(hass, entry):
    _LOGGER.info("local_daikin setting up entry: %s (host: %s)", entry.entry_id, entry.data.get("host", "unknown"))
    hass.data.setdefault("local_daikin", {})[entry.entry_id] = {
         "config": entry.data   
    }
    await hass.config_entries.async_forward_entry_setups(entry, ["climate", "switch", "sensor", "select"])
    _LOGGER.info("local_daikin entry setup complete: %s", entry.entry_id)
    return True

async def async_unload_entry(hass, entry):
    _LOGGER.info("local_daikin unloading entry: %s", entry.entry_id)
    unload_ok = all(
        await asyncio.gather(*[
            hass.config_entries.async_forward_entry_unload(entry, platform)
            for platform in ("climate", "switch", "sensor", "select")
        ])
    )
    if unload_ok:
        hass.data["local_daikin"].pop(entry.entry_id)
        _LOGGER.info("local_daikin entry unloaded successfully: %s", entry.entry_id)
    else:
        _LOGGER.warning("local_daikin entry unload failed: %s", entry.entry_id)
    return unload_ok