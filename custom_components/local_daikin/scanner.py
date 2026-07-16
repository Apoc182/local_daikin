"""Discover Daikin LAN adapters on the local IPv4 network."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PATH = "/dsiot/multireq"
DISCOVERY_PAYLOAD = {
    "requests": [{"op": 2, "to": "/dsiot/edge.adp_i"}],
}
DEFAULT_PREFIX = 24
MAX_SCAN_ADDRESSES = 1024
SCAN_CONCURRENCY = 64
# Some Daikin adapters need more than a second to answer after an ARP lookup.
# Keep enough parallelism for a /24 scan while allowing slow LAN adapters through.
REQUEST_TIMEOUT = ClientTimeout(total=4.0, connect=2.0, sock_read=2.0)


class DaikinConnectionError(Exception):
    """Raised when an address does not expose a supported Daikin adapter."""


@dataclass(frozen=True, slots=True)
class DaikinDeviceInfo:
    """Identity returned by a Daikin LAN adapter."""

    ip: str
    mac: str


def uses_legacy_unique_id(unique_id: str | None) -> bool:
    """Return whether a config entry still uses an IP address as identity."""
    if unique_id is None:
        return True
    try:
        ipaddress.ip_address(unique_id)
    except ValueError:
        return False
    return True


def get_default_network(hass: HomeAssistant) -> str | None:
    """Return the HA host's local /24 network when it is available."""
    local_ip = getattr(getattr(hass.config, "api", None), "local_ip", None)
    if not local_ip:
        return None

    try:
        address = ipaddress.ip_address(str(local_ip))
    except ValueError:
        return None

    if address.version != 4:
        return None

    return str(ipaddress.ip_network(f"{address}/{DEFAULT_PREFIX}", strict=False))


def parse_network(value: str) -> ipaddress.IPv4Network:
    """Validate a user-provided IPv4 network for scanning."""
    network = ipaddress.ip_network(value.strip(), strict=False)
    if network.version != 4:
        raise ValueError("Only IPv4 networks are supported")
    if network.num_addresses > MAX_SCAN_ADDRESSES:
        raise ValueError("The network is too large to scan")
    return network


def _find_pn_value(nodes: object, *keys: str) -> object | None:
    """Find a value in Daikin's nested pn/pv/pch response structure."""
    if not isinstance(nodes, list):
        return None

    current_nodes = nodes
    for index, key in enumerate(keys):
        node = next(
            (
                candidate
                for candidate in current_nodes
                if isinstance(candidate, dict) and candidate.get("pn") == key
            ),
            None,
        )
        if node is None:
            return None
        if index == len(keys) - 1:
            return node.get("pv")
        children = node.get("pch")
        if not isinstance(children, list):
            return None
        current_nodes = children
    return None


def _parse_device_info(ip: str, data: object) -> DaikinDeviceInfo:
    """Extract and normalize a Daikin adapter identity."""
    if not isinstance(data, dict):
        raise DaikinConnectionError("The device returned an invalid response")
    responses = data.get("responses")
    if not isinstance(responses, list):
        raise DaikinConnectionError("The device response has no responses list")

    adapter_response = next(
        (
            response
            for response in responses
            if isinstance(response, dict)
            and response.get("fr") == "/dsiot/edge.adp_i"
        ),
        None,
    )
    if adapter_response is None:
        raise DaikinConnectionError("The address is not a supported Daikin adapter")

    raw_mac = _find_pn_value(adapter_response.get("pc"), "adp_i", "mac")
    if not isinstance(raw_mac, str) or not raw_mac.strip():
        raise DaikinConnectionError("The Daikin adapter did not return a MAC address")

    mac = format_mac(raw_mac)
    if re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac) is None:
        raise DaikinConnectionError("The Daikin adapter returned an invalid MAC")
    return DaikinDeviceInfo(ip=ip, mac=mac)


async def _async_fetch_device_info(session, ip: str) -> DaikinDeviceInfo:
    """Fetch a Daikin adapter identity with an existing HTTP session."""
    try:
        async with session.post(
            f"http://{ip}{DISCOVERY_PATH}",
            json=DISCOVERY_PAYLOAD,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            if response.status != 200:
                raise DaikinConnectionError(
                    f"The device returned HTTP status {response.status}"
                )
            data = await response.json(content_type=None)
    except DaikinConnectionError:
        raise
    except (TimeoutError, ClientError, OSError, ValueError) as err:
        raise DaikinConnectionError("Unable to connect to the Daikin adapter") from err

    return _parse_device_info(ip, data)


async def async_get_device_info(
    hass: HomeAssistant, ip: str
) -> DaikinDeviceInfo:
    """Validate one address and return its stable adapter identity."""
    session = async_get_clientsession(hass)
    return await _async_fetch_device_info(session, ip)


async def _probe_ip(
    session, ip: str, semaphore: asyncio.Semaphore
) -> DaikinDeviceInfo | None:
    """Probe one address and return its identity when it is a Daikin adapter."""
    async with semaphore:
        try:
            return await _async_fetch_device_info(session, ip)
        except DaikinConnectionError:
            return None


async def async_scan_network(
    hass: HomeAssistant, network: ipaddress.IPv4Network
) -> list[DaikinDeviceInfo]:
    """Scan an IPv4 network for Daikin LAN adapters."""
    session = async_get_clientsession(hass)
    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)
    addresses: Iterable[ipaddress.IPv4Address] = network.hosts()
    results = await asyncio.gather(
        *(_probe_ip(session, str(ip), semaphore) for ip in addresses)
    )
    found = sorted(
        (device for device in results if device is not None),
        key=lambda device: ipaddress.ip_address(device.ip),
    )
    _LOGGER.info(
        "Local Daikin scan found %d adapter(s): %s",
        len(found),
        [device.ip for device in found],
    )
    return found
