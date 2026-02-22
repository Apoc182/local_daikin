from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature, PERCENTAGE, UnitOfTime, UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceInfo
import logging

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

async def async_setup_entry(hass, entry, async_add_entities):
    ip = entry.data["ip_address"]
    async_add_entities([
        DaikinOutdoorTempSensor(hass, entry.entry_id, ip),
        DaikinEnergyTodaySensor(hass, entry.entry_id, ip),
        DaikinCurrentHumiditySensor(hass, entry.entry_id, ip),
        DaikinIndoorTempSensor(hass, entry.entry_id, ip),
        DaikinRuntimeTodaySensor(hass, entry.entry_id, ip),
        DaikinTargetTempSensor(hass, entry.entry_id, ip),
    ])


class BaseDaikinSensor(SensorEntity):
    """Base sensor that reads cached state from the climate entity (no extra HTTP calls)."""

    def __init__(self, hass, entry_id, ip, name_suffix, unique_id_suffix):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin {name_suffix} ({ip})"
        self._attr_unique_id = f"daikin_{unique_id_suffix}_{ip}"

    def _get_climate_entity(self):
        data = self._hass.data.get("local_daikin", {}).get(self._entry_id, {})
        return data.get("climate_entity")

    @property
    def available(self) -> bool:
        entity = self._get_climate_entity()
        return entity is not None and entity.available

    def update(self):
        """Read cached values from climate entity — do NOT call entity.update()."""
        entity = self._get_climate_entity()
        if entity is None:
            return
        self._read_state(entity)

    def _read_state(self, entity):
        """Override in subclasses to read the relevant value."""
        pass

    @property
    def native_value(self):
        return self._state

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={("local_daikin", self._ip)},
            name="Local Daikin AC",
            manufacturer="Daikin"
        )


class DaikinOutdoorTempSensor(BaseDaikinSensor):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Outside Temp", "outside_temp")
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def _read_state(self, entity):
        self._state = entity.extra_state_attributes.get("outside_temperature")


class DaikinEnergyTodaySensor(BaseDaikinSensor):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Energy Today", "energy_today")
        self._attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_should_poll = True

    def _read_state(self, entity):
        self._state = entity.extra_state_attributes.get("energy_today")


class DaikinCurrentHumiditySensor(BaseDaikinSensor):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Current Humidity", "current_humidity")
        self._attr_native_unit_of_measurement = PERCENTAGE

    def _read_state(self, entity):
        self._state = entity.current_humidity


class DaikinIndoorTempSensor(BaseDaikinSensor):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Indoor Temp", "indoor_temp")
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def _read_state(self, entity):
        self._state = entity.current_temperature


class DaikinRuntimeTodaySensor(BaseDaikinSensor):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Runtime Today", "runtime_today")
        self._attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _read_state(self, entity):
        self._state = entity.extra_state_attributes.get("runtime_today")


class DaikinTargetTempSensor(BaseDaikinSensor):
    def __init__(self, hass, entry_id, ip):
        super().__init__(hass, entry_id, ip, "Target Temp", "target_temp")
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def _read_state(self, entity):
        self._state = entity.target_temperature
