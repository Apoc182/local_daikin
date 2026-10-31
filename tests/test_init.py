"""Tests for Local Daikin config entry identity migration."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.local_daikin import _async_migrate_legacy_unique_id
from custom_components.local_daikin.const import CONF_IP_ADDRESS, DOMAIN
from custom_components.local_daikin.scanner import (
    DaikinConnectionError,
    DaikinDeviceInfo,
)

IP = "192.168.31.71"
MAC = "aa:bb:cc:dd:ee:ff"


async def test_online_legacy_entry_migrates_to_mac(hass: HomeAssistant) -> None:
    """Reachable legacy entries receive the stable adapter identity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=IP,
        data={CONF_IP_ADDRESS: IP},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.local_daikin.async_get_device_info",
        new=AsyncMock(return_value=DaikinDeviceInfo(IP, MAC)),
    ):
        await _async_migrate_legacy_unique_id(hass, entry)

    assert entry.unique_id == MAC


async def test_offline_legacy_entry_defers_migration(hass: HomeAssistant) -> None:
    """A temporary outage never blocks the existing entry from loading."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=IP,
        data={CONF_IP_ADDRESS: IP},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.local_daikin.async_get_device_info",
        new=AsyncMock(side_effect=DaikinConnectionError),
    ):
        await _async_migrate_legacy_unique_id(hass, entry)

    assert entry.unique_id == IP
