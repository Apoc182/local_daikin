"""Discover Daikin LAN adapters on the local IPv4 network."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Iterable

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PATH = "/dsiot/multireq"
DISCOVERY_PAYLOAD = {
    "requests": [{"op": 2, "to": "/dsiot/edge.adp_i"}],
}
DEFAULT_PREFIX = 24
MAX_SCAN_ADDRESSES = 1024
SCAN_CONCURRENCY = 32
REQUEST_TIMEOUT = ClientTimeout(total=1.5, connect=0.4, sock_read=0.8)


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


def _has_daikin_response(data: object) -> bool:
    """Check for the Daikin adapter response marker."""
    if not isinstance(data, dict):
        return False
    responses = data.get("responses")
    if not isinstance(responses, list):
        return False
    return any(
        isinstance(response, dict)
        and response.get("fr") == "/dsiot/edge.adp_i"
        for response in responses
    )


async def _probe_ip(
    session, ip: str, semaphore: asyncio.Semaphore
) -> str | None:
    """Probe one address and return it only when it is a Daikin adapter."""
    async with semaphore:
        try:
            async with session.post(
                f"http://{ip}{DISCOVERY_PATH}",
                json=DISCOVERY_PAYLOAD,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
        except (asyncio.TimeoutError, ClientError, OSError, ValueError):
            return None

    return ip if _has_daikin_response(data) else None


async def async_scan_network(
    hass: HomeAssistant, network: ipaddress.IPv4Network
) -> list[str]:
    """Scan an IPv4 network for Daikin LAN adapters."""
    session = async_get_clientsession(hass)
    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)
    addresses: Iterable[ipaddress.IPv4Address] = network.hosts()
    results = await asyncio.gather(
        *(_probe_ip(session, str(ip), semaphore) for ip in addresses)
    )
    found = sorted(ip for ip in results if ip is not None)
    _LOGGER.info("Local Daikin scan found %d adapter(s): %s", len(found), found)
    return found
