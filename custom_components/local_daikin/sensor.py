from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature, PERCENTAGE, UnitOfTime
from homeassistant.helpers.device_registry import DeviceInfo

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

class DaikinOutdoorTempSensor(SensorEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Outside Temp ({ip})"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_unique_id = f"daikin_outside_temp_{ip}"

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        entity = self._get_climate_entity()
        entity.update()
        self._state = entity.extra_state_attributes.get("outside_temperature")

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

class DaikinEnergyTodaySensor(SensorEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Energy Today ({ip})"
        self._attr_native_unit_of_measurement = "Wh"
        self._attr_unique_id = f"daikin_energy_today_{ip}"

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        entity = self._get_climate_entity()
        entity.update()
        self._state = entity.extra_state_attributes.get("energy_today")

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

class DaikinCurrentHumiditySensor(SensorEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Current Humidity ({ip})"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_unique_id = f"daikin_current_humidity_{ip}"

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        entity = self._get_climate_entity()
        entity.update()
        self._state = entity.current_humidity

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

class DaikinIndoorTempSensor(SensorEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Indoor Temp ({ip})"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_unique_id = f"daikin_indoor_temp_{ip}"

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        entity = self._get_climate_entity()
        entity.update()
        self._state = entity.current_temperature

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

class DaikinRuntimeTodaySensor(SensorEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Runtime Today ({ip})"
        self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        self._attr_unique_id = f"daikin_runtime_today_{ip}"

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        entity = self._get_climate_entity()
        entity.update()
        self._state = entity.extra_state_attributes.get("runtime_today")

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

class DaikinTargetTempSensor(SensorEntity):
    def __init__(self, hass, entry_id, ip):
        self._hass = hass
        self._entry_id = entry_id
        self._ip = ip
        self._state = None
        self._attr_name = f"Daikin Target Temp ({ip})"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_unique_id = f"daikin_target_temp_{ip}"

    def _get_climate_entity(self):
        return self._hass.data["local_daikin"][self._entry_id]["climate_entity"]

    def update(self):
        entity = self._get_climate_entity()
        entity.update()
        self._state = entity.target_temperature

    @property
    def native_value(self):
        return self._state
