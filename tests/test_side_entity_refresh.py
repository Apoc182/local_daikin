"""Side entities re-read the climate cache right after each climate poll."""

from unittest.mock import MagicMock, patch

from requests import RequestException

from custom_components.local_daikin.climate import (
    CLIMATE_UPDATED_SIGNAL,
    LocalDaikin,
    async_follow_climate,
)

IP = "192.168.31.71"
CLIMATE = "custom_components.local_daikin.climate"


def test_update_signals_side_entities_even_when_the_poll_fails():
    climate = LocalDaikin(IP)
    climate.hass = MagicMock()
    with (
        patch(f"{CLIMATE}.requests.post", side_effect=RequestException("down")),
        patch(f"{CLIMATE}.dispatcher_send") as send,
    ):
        climate.update()
    send.assert_called_once_with(climate.hass, CLIMATE_UPDATED_SIGNAL.format(ip=IP))
    assert climate.available is False


def test_follow_climate_refreshes_only_added_entities():
    hass, entry = MagicMock(), MagicMock()
    entry.data = {"ip_address": IP}
    added, pending = MagicMock(), MagicMock()
    pending.hass = None
    with patch(f"{CLIMATE}.async_dispatcher_connect") as connect:
        async_follow_climate(hass, entry, [added, pending])
    signal, refresh = connect.call_args.args[1:]
    assert signal == CLIMATE_UPDATED_SIGNAL.format(ip=IP)
    refresh()
    added.async_schedule_update_ha_state.assert_called_once_with(True)
    pending.async_schedule_update_ha_state.assert_not_called()
    entry.async_on_unload.assert_called_once_with(connect.return_value)
