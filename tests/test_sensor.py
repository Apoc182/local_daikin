"""Tests for the post-off drying end sensor."""

from datetime import UTC, datetime
from types import SimpleNamespace

from homeassistant.components.sensor import SensorDeviceClass

from custom_components.local_daikin.sensor import DaikinPostOffDryingEndSensor


def _sensor(end):
    climate = SimpleNamespace(available=True, post_off_drying_end=end)
    hass = SimpleNamespace(data={"local_daikin": {"e1": {"climate_entity": climate}}})
    return DaikinPostOffDryingEndSensor(hass, "e1", "1.2.3.4")


def test_drying_end_sensor_reads_climate_value():
    end = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    sensor = _sensor(end)
    sensor.update()
    assert sensor.native_value == end


def test_drying_end_sensor_none_when_idle():
    sensor = _sensor(None)
    sensor.update()
    assert sensor.native_value is None


def test_drying_end_sensor_is_timestamp():
    assert _sensor(None).device_class == SensorDeviceClass.TIMESTAMP
