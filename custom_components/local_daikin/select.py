from homeassistant.components.select import SelectEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.climate.const import HVACMode
from datetime import timedelta
import logging
import asyncio

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

async def async_setup_entry(hass, entry, async_add_entities):
    ip = entry.data["ip_address"]
    _LOGGER.info("Waiting for Daikin climate entity to be available for %s", ip)

    # Wait up to 60 seconds for climate entity to register (Daikin units can be very slow)
    for _ in range(600):
        climate_entity = hass.data["local_daikin"][entry.entry_id].get("climate_entity")
        if climate_entity:
            break
        await asyncio.sleep(0.1)
    else:
        _LOGGER.error("Timeout waiting for climate_entity for Daikin %s", ip)
        return

    _LOGGER.info("Setting up Daikin select entities for %s", ip)
    async_add_entities([
        DaikinFanSpeedSelect(hass, entry.entry_id, ip),
        DaikinSwingModeSelect(hass, entry.entry_id, ip),
        DaikinHvacModeSelect(hass, entry.entry_id, ip),
    ])

class BaseDaikinSelect(SelectEntity):
    def __init__(self, hass, entry_id, ip, name_suffix, unique_id_suffix):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._climate = None
        self._attr_name = f"Daikin {name_suffix} ({ip})"
        self._attr_unique_id = f"daikin_{unique_id_suffix}_{ip}"
        self._attr_should_poll = True

    async def async_added_to_hass(self):
        self._climate = self._hass.data["local_daikin"][self._entry_id].get("climate_entity")

    def _get_climate(self):
        return self._climate

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={("local_daikin", self._ip)},
            name="Local Daikin AC",
            manufacturer="Daikin"
        )

class DaikinFanSpeedSelect(BaseDaikinSelect):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Fan Speed", "fan_speed")

    @property
    def current_option(self):
        if not self._climate:
            return None
#        _LOGGER.warning(f"[SelectEntity] current fan_mode = {self._climate.fan_mode}")
        return self._climate.fan_mode

    @property
    def options(self):
        if not self._climate:
#            _LOGGER.warning("[SelectEntity] Climate not initialized")
            return []
##        _LOGGER.warning(f"[SelectEntity] fan_modes = {self._climate.fan_modes}")
        return self._climate.fan_modes

    def select_option(self, option: str):
        _LOGGER.info(f"[FanSpeedSelect] Changing fan mode to {option}")
        if self._climate:
            self._climate.set_fan_mode(option)
            self.schedule_update_ha_state(force_refresh=True)

class DaikinSwingModeSelect(BaseDaikinSelect):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Swing Mode", "swing_mode")

    @property
    def current_option(self):
        if not self._climate:
            return None
#        _LOGGER.warning(f"[SelectEntity] current swing_mode = {self._climate.swing_mode}")
        return self._climate.swing_mode

    @property
    def options(self):
        if not self._climate:
#            _LOGGER.warning("[SelectEntity] Climate not initialized")
            return []
#        _LOGGER.warning(f"[SelectEntity] swing_modes = {self._climate.swing_modes}")
        return self._climate.swing_modes

    def select_option(self, option: str):
        _LOGGER.info(f"[SwingModeSelect] Changing swing mode to {option}")
        if self._climate:
            self._climate.set_swing_mode(option)
            self.schedule_update_ha_state(force_refresh=True)

class DaikinHvacModeSelect(BaseDaikinSelect):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "HVAC Mode", "hvac_mode")

    @property
    def current_option(self):
        if not self._climate:
            return None
        return self._climate.hvac_mode

    @property
    def options(self):
        if not self._climate:
            return []
        return self._climate.hvac_modes

    def select_option(self, option: str):
        _LOGGER.info(f"[HVACModeSelect] Changing HVAC mode to {option}")
        if self._climate:
            self._climate.set_hvac_mode(HVACMode(option))
            self.schedule_update_ha_state(force_refresh=True)
