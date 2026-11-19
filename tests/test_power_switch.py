"""Tests for the Power switch state around a power-only turn-on."""

from unittest.mock import MagicMock, patch

from homeassistant.components.climate.const import HVACMode

from custom_components.local_daikin.climate import LocalDaikin
from custom_components.local_daikin.switch import DaikinPowerSwitch

IP = "192.168.31.71"
POST_PATH = "custom_components.local_daikin.climate.requests.post"


def _switch_for_off_unit():
    climate = LocalDaikin(IP)
    climate._hvac_mode = HVACMode.OFF
    hass = MagicMock()
    hass.data = {"local_daikin": {"entry-1": {"climate_entity": climate}}}
    switch = DaikinPowerSwitch(hass, "entry-1", IP)
    switch.hass = hass
    switch.schedule_update_ha_state = MagicMock()
    return climate, switch


def _accepted_post():
    post = MagicMock()
    post.return_value.json.return_value = {"responses": [{"rsc": 2004}]}
    return post


def test_power_switch_stays_on_until_the_unit_is_polled():
    """turn_on sends only the power bit, so the climate cache keeps "off"
    until the next poll; the forced refresh must not flip the switch back."""
    climate, switch = _switch_for_off_unit()
    with patch(POST_PATH, _accepted_post()):
        switch.turn_on()
    switch.update()  # HA's refresh right after the service call
    assert switch.is_on is True


def test_power_switch_follows_a_poll_made_after_the_command():
    climate, switch = _switch_for_off_unit()
    with patch(POST_PATH, _accepted_post()):
        switch.turn_on()
    # A poll that started after the command reports the unit still off.
    climate._polled_at = float("inf")
    switch.update()
    assert switch.is_on is False
