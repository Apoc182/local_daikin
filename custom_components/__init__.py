import asyncio

async def async_setup(hass, config):
    return True

async def async_setup_entry(hass, entry):
    hass.data.setdefault("local_daikin", {})[entry.entry_id] = {
         "config": entry.data   
    }
    await hass.config_entries.async_forward_entry_setups(entry, ["climate", "switch", "sensor", "select"])
    return True

async def async_unload_entry(hass, entry):
    unload_ok = all(
        await asyncio.gather(*[
            hass.config_entries.async_forward_entry_unload(entry, platform)
            for platform in ("climate", "switch", "sensor", "select")
        ])
    )
    if unload_ok:
        hass.data["local_daikin"].pop(entry.entry_id)
    return unload_ok