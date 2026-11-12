import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.climate.const import HVACMode
from datetime import timedelta
from time import monotonic

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

async def async_setup_entry(hass, entry, async_add_entities):
    _LOGGER.info("Setting up Daikin switches for %s", entry.data["ip_address"])
    features = [
        cls(hass, entry.entry_id, entry.data["ip_address"])
        for cls in (
            DaikinComfortSwitch,
            DaikinEconoSwitch,
            DaikinOutdoorQuietSwitch,
            DaikinPowerfulSwitch,
        )
    ]
    for feature_switch in features:
        feature_switch._group = features
    async_add_entities([
        DaikinPowerSwitch(hass, entry.entry_id, entry.data["ip_address"]),
        DaikinQuietFanSwitch(hass, entry.entry_id, entry.data["ip_address"]),
        *features,
    ])


class DaikinPowerSwitch(SwitchEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Power ({ip})"
        self._commanded_at = None  # monotonic() of the last accepted command
        self._attr_unique_id = f"daikin_power_{ip}"
        self._attr_should_poll = True

    def _get_climate_entity(self):
        data = self._hass.data.get("local_daikin", {}).get(self._entry_id, {})
        return data.get("climate_entity")

    @property
    def available(self) -> bool:
        entity = self._get_climate_entity()
        return entity is not None and entity.available

    def update(self):
        """Read cached state from climate entity — no extra HTTP call."""
        entity = self._get_climate_entity()
        if entity is None:
            return
        # A power-only turn_on leaves the cached mode "off" (the mode the unit
        # resumes is unknown), so keep the commanded state until a poll that
        # started after the command has read the unit.
        if self._commanded_at is not None and (
            entity._polled_at is None or entity._polled_at < self._commanded_at
        ):
            return
        self._commanded_at = None
        self._state = entity.hvac_mode != "off"

    def turn_on(self, **kwargs):
        entity = self._get_climate_entity()
        if entity is None:
            return
        entity.turn_on()
        self._state = True
        self._commanded_at = monotonic()
        self.schedule_update_ha_state(force_refresh=True)

    def turn_off(self, **kwargs):
        entity = self._get_climate_entity()
        if entity is None:
            return
        entity.turn_off()
        self._state = False
        self._commanded_at = monotonic()
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

class DaikinFeatureSwitch(SwitchEntity):
    """Base switch for a climate feature toggle (comfort, econo, ...).

    Reads the cached feature state from the climate entity. A feature the
    model does not expose stays unknown (is_on is None) instead of a fake off.
    """

    feature = None
    name_suffix = None
    unique_id_suffix = None

    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin {self.name_suffix} ({ip})"
        self._attr_unique_id = f"daikin_{self.unique_id_suffix}_{ip}"
        self._attr_should_poll = True
        self._group = ()  # all feature switches of this unit, set at setup

    def _get_climate_entity(self):
        data = self._hass.data.get("local_daikin", {}).get(self._entry_id, {})
        return data.get("climate_entity")

    @property
    def available(self):
        entity = self._get_climate_entity()
        return entity is not None and entity.available

    def update(self):
        """Read cached state from climate entity — no extra HTTP call."""
        entity = self._get_climate_entity()
        if entity is None:
            return
        self._state = (
            None
            if entity.extra_state_attributes.get(self.feature) is None
            else entity.extra_state_attributes[self.feature] == "on"
        )

    def turn_on(self, **kwargs):
        entity = self._get_climate_entity()
        if entity is None:
            return
        entity.set_feature(self.feature, True)
        if entity.hass is not None:  # climate exposes features as attributes
            entity.schedule_update_ha_state()
        self._state = True
        self.schedule_update_ha_state(force_refresh=True)
        # Turning a feature on may clear its exclusive counterparts.
        for other in self._group:
            if other is not self and other.hass is not None:
                other.schedule_update_ha_state(force_refresh=True)

    def turn_off(self, **kwargs):
        entity = self._get_climate_entity()
        if entity is None:
            return
        entity.set_feature(self.feature, False)
        if entity.hass is not None:
            entity.schedule_update_ha_state()
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


class DaikinComfortSwitch(DaikinFeatureSwitch):
    feature = "comfort"
    name_suffix = "Comfort Airflow"
    unique_id_suffix = "comfort"


class DaikinEconoSwitch(DaikinFeatureSwitch):
    feature = "econo"
    name_suffix = "Econo"
    unique_id_suffix = "econo"


class DaikinOutdoorQuietSwitch(DaikinFeatureSwitch):
    feature = "outdoor_quiet"
    name_suffix = "Outdoor Unit Quiet"
    unique_id_suffix = "outdoor_quiet"


class DaikinPowerfulSwitch(DaikinFeatureSwitch):
    feature = "powerful"
    name_suffix = "Powerful"
    unique_id_suffix = "powerful"


class DaikinQuietFanSwitch(SwitchEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Quiet Fan ({ip})"
        self._attr_unique_id = f"daikin_quietfan_{ip}"
        self._attr_should_poll = True

    def _get_climate_entity(self):
        data = self._hass.data.get("local_daikin", {}).get(self._entry_id, {})
        return data.get("climate_entity")

    @property
    def available(self) -> bool:
        entity = self._get_climate_entity()
        return entity is not None and entity.available

    def update(self):
        """Read cached state from climate entity — no extra HTTP call."""
        entity = self._get_climate_entity()
        if entity is None:
            return
        self._state = entity.fan_mode == "Quiet"

    def turn_on(self, **kwargs):
        """Set fan mode to Quiet."""
        entity = self._get_climate_entity()
        if entity is None:
            return
        entity.set_fan_mode("Quiet")
        self._state = True
        self.schedule_update_ha_state(force_refresh=True)

    def turn_off(self, **kwargs):
        """Set fan mode to Auto."""
        entity = self._get_climate_entity()
        if entity is None:
            return
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
