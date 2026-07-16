"""Tests for Local Daikin network discovery."""

import asyncio
import ipaddress
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers.device_registry import format_mac

from custom_components.local_daikin.scanner import (
    REQUEST_TIMEOUT,
    SCAN_CONCURRENCY,
    DaikinConnectionError,
    DaikinDeviceInfo,
    _async_fetch_device_info,
    _find_pn_value,
    _parse_device_info,
    _probe_ip,
    async_get_device_info,
    async_scan_network,
    get_default_network,
    parse_network,
    uses_legacy_unique_id,
)

MAC = "aa:bb:cc:dd:ee:ff"


def daikin_response(raw_mac: str = "AABBCCDDEEFF") -> dict:
    """Build the adapter identity response used by Daikin devices."""
    return {
        "responses": [
            {
                "fr": "/dsiot/edge.adp_i",
                "pc": [
                    {
                        "pn": "adp_i",
                        "pch": [{"pn": "mac", "pv": raw_mac}],
                    }
                ],
            }
        ]
    }


def test_parse_device_info_uses_mac_as_identity() -> None:
    """A supported response produces a normalized stable identity."""
    device = _parse_device_info("192.168.31.71", daikin_response())

    assert device == DaikinDeviceInfo(
        ip="192.168.31.71", mac=format_mac("AABBCCDDEEFF")
    )


@pytest.mark.parametrize(
    "data", [None, {}, {"responses": []}, {"responses": [{}]}]
)
def test_parse_device_info_rejects_non_daikin_responses(data: object) -> None:
    """An address without a valid adapter identity is rejected."""
    with pytest.raises(DaikinConnectionError):
        _parse_device_info("192.168.31.71", data)


@pytest.mark.parametrize("raw_mac", ["", "not-a-mac", "GGGGGGGGGGGG"])
def test_parse_device_info_rejects_invalid_mac(raw_mac: str) -> None:
    """The adapter marker alone is insufficient without a valid MAC."""
    with pytest.raises(DaikinConnectionError):
        _parse_device_info("192.168.31.71", daikin_response(raw_mac))


def test_parse_network_accepts_only_bounded_ipv4_networks() -> None:
    """Network scans stay within the IPv4 size supported by the UI."""
    assert str(parse_network("192.168.31.71/24")) == "192.168.31.0/24"

    with pytest.raises(ValueError):
        parse_network("2001:db8::/64")
    with pytest.raises(ValueError):
        parse_network("10.0.0.0/21")


@pytest.mark.parametrize(
    ("local_ip", "expected"),
    [
        ("192.168.31.79", "192.168.31.0/24"),
        (None, None),
        ("not-an-ip", None),
        ("2001:db8::1", None),
    ],
)
def test_default_network_uses_home_assistant_ipv4(
    local_ip: str | None, expected: str | None
) -> None:
    """The suggested scan range is derived only from a valid local IPv4."""
    hass = SimpleNamespace(
        config=SimpleNamespace(api=SimpleNamespace(local_ip=local_ip))
    )
    assert get_default_network(hass) == expected


def test_find_pn_value_handles_malformed_trees() -> None:
    """Malformed adapter payloads fail closed without parser exceptions."""
    assert _find_pn_value(None, "adp_i") is None
    assert _find_pn_value([], "adp_i") is None
    assert _find_pn_value([{}]) is None
    assert _find_pn_value([{"pn": "other"}], "adp_i") is None
    assert _find_pn_value([{"pn": "adp_i", "pch": {}}], "adp_i", "mac") is None


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [(None, True), ("192.168.31.71", True), (MAC, False)],
)
def test_legacy_unique_id_detection(
    unique_id: str | None, expected: bool
) -> None:
    """Only missing and IP-based identities are considered legacy."""
    assert uses_legacy_unique_id(unique_id) is expected


class FakeResponse:
    """Minimal aiohttp response context manager for request tests."""

    def __init__(self, status: int, data: object) -> None:
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def json(self, content_type=None) -> object:
        return self._data


class FakeSession:
    """Minimal aiohttp session for request tests."""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def post(self, *args, **kwargs) -> FakeResponse:
        return self.response


async def test_fetch_device_info_validates_http_response() -> None:
    """The probe returns identity only after a successful DSIOT response."""
    device = await _async_fetch_device_info(
        FakeSession(FakeResponse(200, daikin_response())), "192.168.31.71"
    )
    assert device.mac == format_mac("AABBCCDDEEFF")

    with pytest.raises(DaikinConnectionError):
        await _async_fetch_device_info(
            FakeSession(FakeResponse(404, {})), "192.168.31.72"
        )


def test_discovery_timeout_allows_slow_lan_adapters() -> None:
    """Discovery tolerates adapters delayed by ARP and Wi-Fi wake-up."""
    assert SCAN_CONCURRENCY == 8
    assert REQUEST_TIMEOUT.total == 4.0
    assert REQUEST_TIMEOUT.connect == 2.0
    assert REQUEST_TIMEOUT.sock_read == 2.0


async def test_fetch_device_info_maps_network_errors() -> None:
    """Expected transport failures become a config-flow connection error."""

    class BrokenSession:
        def post(self, *args, **kwargs):
            raise OSError("offline")

    with pytest.raises(DaikinConnectionError):
        await _async_fetch_device_info(BrokenSession(), "192.168.31.71")


async def test_public_probe_helpers_share_validation() -> None:
    """Manual validation and scan probes use the same response parser."""
    session = FakeSession(FakeResponse(200, daikin_response()))
    with patch(
        "custom_components.local_daikin.scanner.async_get_clientsession",
        return_value=session,
    ):
        device = await async_get_device_info(object(), "192.168.31.71")
    assert device.mac == format_mac("AABBCCDDEEFF")

    assert await _probe_ip(
        session, "192.168.31.71", asyncio.Semaphore(1)
    ) == device
    assert (
        await _probe_ip(
            FakeSession(FakeResponse(404, {})),
            "192.168.31.72",
            asyncio.Semaphore(1),
        )
        is None
    )


async def test_scan_returns_devices_in_numeric_ip_order() -> None:
    """Concurrent probes return structured identities in stable address order."""
    devices = {
        "192.168.31.1": DaikinDeviceInfo("192.168.31.1", MAC),
        "192.168.31.2": DaikinDeviceInfo(
            "192.168.31.2", "aa:bb:cc:dd:ee:02"
        ),
    }

    async def probe(_session, ip: str, _semaphore):
        return devices.get(ip)

    with (
        patch(
            "custom_components.local_daikin.scanner.async_get_clientsession",
            return_value=object(),
        ),
        patch(
            "custom_components.local_daikin.scanner._probe_ip",
            new=AsyncMock(side_effect=probe),
        ),
    ):
        result = await async_scan_network(
            object(), ipaddress.ip_network("192.168.31.0/30")
        )

    assert [device.ip for device in result] == ["192.168.31.1", "192.168.31.2"]
