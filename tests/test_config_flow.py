"""Tests for the Local Daikin configuration flows."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.local_daikin.config_flow import AddEntriesResult
from custom_components.local_daikin.const import CONF_IP_ADDRESS, DOMAIN
from custom_components.local_daikin.scanner import (
    DaikinConnectionError,
    DaikinDeviceInfo,
)

OLD_IP = "192.168.31.71"
NEW_IP = "192.168.31.72"
MAC = "aa:bb:cc:dd:ee:ff"
OTHER_MAC = "11:22:33:44:55:66"


async def open_step(hass: HomeAssistant, step_id: str) -> dict:
    """Start the user flow and choose one menu option."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )


async def test_manual_setup_validates_device_and_uses_mac(
    hass: HomeAssistant,
) -> None:
    """Manual setup verifies DSIOT before creating a stable config entry."""
    result = await open_step(hass, "manual")

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=AsyncMock(return_value=DaikinDeviceInfo(OLD_IP, MAC)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: OLD_IP}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_IP_ADDRESS: OLD_IP}
    assert result["result"].unique_id == MAC


async def test_manual_setup_rejects_ipv6_without_connecting(
    hass: HomeAssistant,
) -> None:
    """The form no longer advertises or accepts unsupported IPv6 addresses."""
    result = await open_step(hass, "manual")
    get_device = AsyncMock()

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=get_device,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: "2001:db8::1"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_IP_ADDRESS: "invalid_ip"}
    get_device.assert_not_awaited()


async def test_manual_setup_reports_connection_failure(
    hass: HomeAssistant,
) -> None:
    """A syntactically valid but unreachable address is not saved."""
    result = await open_step(hass, "manual")

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=AsyncMock(side_effect=DaikinConnectionError),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: OLD_IP}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_manual_setup_rejects_duplicate_mac(hass: HomeAssistant) -> None:
    """A device cannot be added twice after its IP address changes."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    ).add_to_hass(hass)
    result = await open_step(hass, "manual")

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=AsyncMock(return_value=DaikinDeviceInfo(NEW_IP, MAC)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: NEW_IP}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_manual_setup_rejects_duplicate_ip_before_connecting(
    hass: HomeAssistant,
) -> None:
    """An existing address is rejected without another network request."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    ).add_to_hass(hass)
    result = await open_step(hass, "manual")
    get_device = AsyncMock()

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=get_device,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: OLD_IP}
        )

    assert result["reason"] == "already_configured"
    get_device.assert_not_awaited()


async def test_manual_setup_reports_unexpected_validation_error(
    hass: HomeAssistant,
) -> None:
    """Unexpected validation failures remain recoverable in the form."""
    result = await open_step(hass, "manual")

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=AsyncMock(side_effect=RuntimeError("unexpected")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: OLD_IP}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Start reconfiguration for an existing entry."""
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )


async def test_reconfigure_verifies_same_device(hass: HomeAssistant) -> None:
    """A stable entry accepts a new address only for the same adapter MAC."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    )
    entry.add_to_hass(hass)
    result = await start_reconfigure(hass, entry)

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=AsyncMock(return_value=DaikinDeviceInfo(NEW_IP, MAC)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: NEW_IP}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_IP_ADDRESS] == NEW_IP
    assert entry.unique_id == MAC


async def test_reconfigure_rejects_different_device(hass: HomeAssistant) -> None:
    """Changing an address cannot silently replace the physical device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    )
    entry.add_to_hass(hass)
    result = await start_reconfigure(hass, entry)

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=AsyncMock(return_value=DaikinDeviceInfo(NEW_IP, OTHER_MAC)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: NEW_IP}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_IP_ADDRESS] == OLD_IP
    assert entry.unique_id == MAC


async def test_reconfigure_migrates_legacy_ip_identity(
    hass: HomeAssistant,
) -> None:
    """A legacy entry moves to the adapter MAC during reconfiguration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=OLD_IP,
        data={CONF_IP_ADDRESS: OLD_IP},
    )
    entry.add_to_hass(hass)
    result = await start_reconfigure(hass, entry)

    with patch(
        "custom_components.local_daikin.config_flow.async_get_device_info",
        new=AsyncMock(return_value=DaikinDeviceInfo(NEW_IP, MAC)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: NEW_IP}
        )

    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == MAC
    assert entry.data[CONF_IP_ADDRESS] == NEW_IP


async def test_reconfigure_rejects_another_entry_ip(hass: HomeAssistant) -> None:
    """Reconfiguration cannot steal the address of another entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    )
    entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=OTHER_MAC,
        data={CONF_IP_ADDRESS: NEW_IP},
    ).add_to_hass(hass)
    result = await start_reconfigure(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IP_ADDRESS: NEW_IP}
    )

    assert result["reason"] == "already_configured"
    assert entry.data[CONF_IP_ADDRESS] == OLD_IP


async def test_reconfigure_rejects_ipv6(hass: HomeAssistant) -> None:
    """Reconfiguration preserves the current entry for unsupported IPv6."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    )
    entry.add_to_hass(hass)
    result = await start_reconfigure(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IP_ADDRESS: "2001:db8::1"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_IP_ADDRESS: "invalid_ip"}
    assert entry.data[CONF_IP_ADDRESS] == OLD_IP


async def test_scan_reports_partial_addition(hass: HomeAssistant) -> None:
    """A partially successful scan identifies failed addresses."""
    devices = [
        DaikinDeviceInfo(OLD_IP, MAC),
        DaikinDeviceInfo(NEW_IP, OTHER_MAC),
    ]
    result = await open_step(hass, "scan")

    with (
        patch(
            "custom_components.local_daikin.config_flow.async_scan_network",
            new=AsyncMock(return_value=devices),
        ),
        patch(
            "custom_components.local_daikin.config_flow.DaikinConfigFlow._async_add_entries",
            new=AsyncMock(
                return_value=AddEntriesResult(
                    added=(OLD_IP,), skipped=(), failed=(NEW_IP,)
                )
            ),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "192.168.31.0/24"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "scan_partial"
    assert result["description_placeholders"] == {
        "added": "1",
        "skipped": "0",
        "failed": "1",
        "failed_ips": NEW_IP,
    }


async def test_scan_adds_all_verified_devices(hass: HomeAssistant) -> None:
    """Verified scan results create one stable config entry per adapter."""
    devices = [
        DaikinDeviceInfo(OLD_IP, MAC),
        DaikinDeviceInfo(NEW_IP, OTHER_MAC),
    ]
    result = await open_step(hass, "scan")

    with patch(
        "custom_components.local_daikin.config_flow.async_scan_network",
        new=AsyncMock(return_value=devices),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "192.168.31.0/24"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "scan_complete"
    assert result["description_placeholders"]["added"] == "2"
    entries = hass.config_entries.async_entries(DOMAIN)
    assert {entry.unique_id for entry in entries} == {MAC, OTHER_MAC}
    assert {entry.data[CONF_IP_ADDRESS] for entry in entries} == {OLD_IP, NEW_IP}


async def test_scan_filters_devices_already_configured(
    hass: HomeAssistant,
) -> None:
    """A verified device already present by IP and MAC is not added again."""
    device = DaikinDeviceInfo(OLD_IP, MAC)
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    ).add_to_hass(hass)
    result = await open_step(hass, "scan")

    with patch(
        "custom_components.local_daikin.config_flow.async_scan_network",
        new=AsyncMock(return_value=[device]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "192.168.31.0/24"}
        )

    assert result["reason"] == "all_configured"


async def test_internal_discovery_rejects_duplicate_ip(
    hass: HomeAssistant,
) -> None:
    """The internal scan source applies the same duplicate-address guard."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={CONF_IP_ADDRESS: OLD_IP},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_IP_ADDRESS: OLD_IP, "mac": OTHER_MAC},
    )

    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("network", "error"),
    [("not-a-network", "invalid_network"), ("10.0.0.0/21", "invalid_network")],
)
async def test_scan_rejects_invalid_network(
    hass: HomeAssistant, network: str, error: str
) -> None:
    """Invalid or excessive scan ranges remain editable in the form."""
    result = await open_step(hass, "scan")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"network": network}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"network": error}


async def test_scan_reports_no_devices(hass: HomeAssistant) -> None:
    """An empty network scan has a distinct user-facing result."""
    result = await open_step(hass, "scan")
    with patch(
        "custom_components.local_daikin.config_flow.async_scan_network",
        new=AsyncMock(return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "192.168.31.0/24"}
        )

    assert result["reason"] == "no_devices_found"


async def test_scan_reports_scanner_exception(hass: HomeAssistant) -> None:
    """An unexpected scanner exception returns to a recoverable form."""
    result = await open_step(hass, "scan")
    with patch(
        "custom_components.local_daikin.config_flow.async_scan_network",
        new=AsyncMock(side_effect=RuntimeError("scan failed")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "192.168.31.0/24"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "scan_failed"}


@pytest.mark.parametrize(
    ("nested_result", "expected_reason", "expected_error"),
    [
        (
            {"type": FlowResultType.ABORT, "reason": "already_configured"},
            "all_configured",
            None,
        ),
        (
            {"type": FlowResultType.FORM, "flow_id": "unfinished"},
            None,
            "scan_add_failed",
        ),
    ],
)
async def test_scan_handles_nested_flow_outcomes(
    hass: HomeAssistant,
    nested_result: dict,
    expected_reason: str | None,
    expected_error: str | None,
) -> None:
    """Per-device flow results are preserved as skipped or failed."""
    result = await open_step(hass, "scan")
    device = DaikinDeviceInfo(OLD_IP, MAC)

    with (
        patch(
            "custom_components.local_daikin.config_flow.async_scan_network",
            new=AsyncMock(return_value=[device]),
        ),
        patch.object(
            hass.config_entries.flow,
            "async_init",
            new=AsyncMock(return_value=nested_result),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "192.168.31.0/24"}
        )

    if expected_reason is not None:
        assert result["reason"] == expected_reason
    else:
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": expected_error}
        assert result["description_placeholders"]["failed_ips"] == OLD_IP


async def test_scan_handles_nested_flow_exception(hass: HomeAssistant) -> None:
    """One failed discovery flow returns a recoverable scan error."""
    result = await open_step(hass, "scan")
    device = DaikinDeviceInfo(OLD_IP, MAC)

    with (
        patch(
            "custom_components.local_daikin.config_flow.async_scan_network",
            new=AsyncMock(return_value=[device]),
        ),
        patch.object(
            hass.config_entries.flow,
            "async_init",
            new=AsyncMock(side_effect=RuntimeError("flow failed")),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"network": "192.168.31.0/24"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "scan_add_failed"}
    assert result["description_placeholders"]["failed_ips"] == OLD_IP
