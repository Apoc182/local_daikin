import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.climate.const import HVACMode
from datetime import timedelta

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

async def async_setup_entry(hass, entry, async_add_entities):
    _LOGGER.info("Setting up Daikin switches for %s", entry.data["ip_address"])
    async_add_entities([
        DaikinPowerSwitch(hass, entry.entry_id, entry.data["ip_address"]),
        DaikinQuietFanSwitch(hass, entry.entry_id, entry.data["ip_address"]),
    ])



class DaikinPowerSwitch(SwitchEntity):
    def __init__(self, hass, entry_id, ip):

        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Power ({ip})"
        self._attr_unique_id = f"daikin_power_{ip}"
        self._attr_should_poll = True 
        _LOGGER.info("Created DaikinPowerSwitch for %s", self._ip)

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        entity = self._get_climate_entity()
        entity.update()
        _LOGGER.info(f"[PowerSwitch] Climate hvac_mode: {entity.hvac_mode}")
        self._state = entity.hvac_mode != "off"

    def turn_on(self, **kwargs):
        entity = self._get_climate_entity()
        entity.turn_on()
        self._state = True
        self.schedule_update_ha_state(force_refresh=True)

    def turn_off(self, **kwargs):
        entity = self._get_climate_entity()
        entity.turn_off()
        self._state = False
        self.schedule_update_ha_state(force_refresh=True)

    @property
    def is_on(self):
        return self._state

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={("local_daikin", self._ip)},
            name="Local Daikin AC",
            manufacturer="Daikin"
        )

class DaikinQuietFanSwitch(SwitchEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Quiet Fan ({ip})"
        self._attr_unique_id = f"daikin_quietfan_{ip}"
        self._attr_should_poll = True 
        _LOGGER.info("Created DaikinQuietFanSwitch for %s", self._ip)

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        """Sync with current fan mode from the climate entity."""
        entity = self._get_climate_entity()
        entity.update()
        self._state = entity.fan_mode == "Quiet"

    def turn_on(self, **kwargs):
        """Set fan mode to Quiet."""
        entity = self._get_climate_entity()
        entity.set_fan_mode("Quiet")
        self._state = True
        self.schedule_update_ha_state(force_refresh=True)

    def turn_off(self, **kwargs):
        """Set fan mode to Auto."""
        entity = self._get_climate_entity()
        entity.set_fan_mode("Auto")
        self._state = False
        self.schedule_update_ha_state(force_refresh=True)

    @property
    def is_on(self):
        return self._state

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={("local_daikin", self._ip)},
            name="Local Daikin AC",
            manufacturer="Daikin"
        )