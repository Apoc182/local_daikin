"""Read-only feature states (features this unit reports but does not let set)."""

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .climate import async_setup_feature_entities
from .switch import FEATURE_SWITCHES

SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(hass, entry, async_add_entities):
    ip = entry.data["ip_address"]

    def build(access):
        return [
            DaikinFeatureBinarySensor(hass, entry.entry_id, ip, cls)
            for cls in FEATURE_SWITCHES
            if access.get(cls.feature) == "read"
        ]

    async_setup_feature_entities(hass, entry, async_add_entities, build)


class DaikinFeatureBinarySensor(BinarySensorEntity):
    """Feature state the unit reports as read-only (leaf pt=3)."""

    def __init__(self, hass, entry_id, ip, switch_cls):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self.feature = switch_cls.feature
        self._state = None
        self._attr_name = f"Daikin {switch_cls.name_suffix} ({ip})"
        self._attr_unique_id = f"daikin_{switch_cls.unique_id_suffix}_{ip}"
        self._attr_should_poll = True

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
        value = entity._features.get(self.feature)
        self._state = None if value is None else value == "on"

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
