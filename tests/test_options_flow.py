"""Tests for the Local Daikin options flow and update listener."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.local_daikin import _async_update_listener
from custom_components.local_daikin.const import (
    CONF_IP_ADDRESS,
    CONF_POST_OFF_DRYING,
    CONF_POST_OFF_DRYING_MINUTES,
    DOMAIN,
)


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_IP_ADDRESS: "192.168.1.2"})
    entry.add_to_hass(hass)
    return entry


async def test_options_form_defaults(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    defaults = {k.schema: k.default() for k in result["data_schema"].schema}
    assert defaults == {CONF_POST_OFF_DRYING: False, CONF_POST_OFF_DRYING_MINUTES: 60}


async def test_options_saved(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {CONF_POST_OFF_DRYING: True, CONF_POST_OFF_DRYING_MINUTES: 30}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == user_input


@pytest.mark.parametrize("minutes", [4, 181])
async def test_options_duration_out_of_range(hass: HomeAssistant, minutes) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_POST_OFF_DRYING: True, CONF_POST_OFF_DRYING_MINUTES: minutes},
        )


async def test_update_listener_reloads(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock()
    ) as reload:
        await _async_update_listener(hass, entry)
    reload.assert_awaited_once_with(entry.entry_id)


def test_no_options_flow_with_reload_import() -> None:
    src = Path("custom_components/local_daikin/config_flow.py").read_text()
    assert "OptionsFlowWithReload" not in src
