"""Config flow for Local Daikin."""

from __future__ import annotations

import ipaddress
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.data_entry_flow import FlowResultType, UnknownFlow

from .const import CONF_IP_ADDRESS, DOMAIN
from .scanner import (
    DaikinConnectionError,
    DaikinDeviceInfo,
    async_get_device_info,
    async_scan_network,
    get_default_network,
    parse_network,
    uses_legacy_unique_id,
)

CONF_NETWORK = "network"
_LOGGER = logging.getLogger(__name__)


def _normalise_ip(value: str) -> str:
    """Return a canonical IPv4 address or raise ValueError."""
    address = ipaddress.ip_address(value.strip())
    if address.version != 4:
        raise ValueError("Only IPv4 addresses are supported")
    return str(address)


@dataclass(frozen=True, slots=True)
class AddEntriesResult:
    """Results from adding all devices found by one network scan."""

    added: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]


def _schema(default: str | None = None) -> vol.Schema:
    """Build the IP address form schema."""
    field = vol.Required(CONF_IP_ADDRESS)
    if default is not None:
        field = vol.Required(CONF_IP_ADDRESS, default=default)
    return vol.Schema({field: str})


class DaikinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle adding and reconfiguring a Daikin LAN adapter."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose manual setup or automatic local network discovery."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["manual", "scan"],
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add a Daikin LAN adapter from a manually entered IP address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                ip = _normalise_ip(user_input[CONF_IP_ADDRESS])
            except ValueError:
                errors[CONF_IP_ADDRESS] = "invalid_ip"
            else:
                if self._is_ip_configured(ip):
                    return self.async_abort(reason="already_configured")

                device = await self._async_validate_device(ip, errors)
                if device is not None:
                    await self.async_set_unique_id(device.mac)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Daikin {ip}", data={CONF_IP_ADDRESS: ip}
                    )

        return self.async_show_form(
            step_id="manual",
            data_schema=_schema(),
            errors=errors,
        )

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Scan the local network and add every new Daikin adapter."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] | None = None
        default_network = get_default_network(self.hass) or ""

        if user_input is not None:
            try:
                network = parse_network(user_input[CONF_NETWORK])
            except ValueError:
                errors[CONF_NETWORK] = "invalid_network"
            else:
                try:
                    discovered = await async_scan_network(self.hass, network)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unable to scan network %s", network)
                    errors["base"] = "scan_failed"
                else:
                    if not discovered:
                        return self.async_abort(reason="no_devices_found")

                    new_devices = [
                        device
                        for device in discovered
                        if not self._is_ip_configured(device.ip)
                        and not self._is_unique_id_configured(device.mac)
                    ]
                    if not new_devices:
                        return self.async_abort(reason="all_configured")

                    result = await self._async_add_entries(new_devices)
                    placeholders = {
                        "added": str(len(result.added)),
                        "skipped": str(len(result.skipped)),
                        "failed": str(len(result.failed)),
                        "failed_ips": ", ".join(result.failed) or "-",
                    }
                    if result.failed and result.added:
                        return self.async_abort(
                            reason="scan_partial",
                            description_placeholders=placeholders,
                        )
                    if result.failed:
                        errors["base"] = "scan_add_failed"
                        description_placeholders = placeholders
                    elif result.added:
                        return self.async_abort(
                            reason="scan_complete",
                            description_placeholders=placeholders,
                        )
                    else:
                        return self.async_abort(reason="all_configured")

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {vol.Required(CONF_NETWORK, default=default_network): str}
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        """Add one adapter that was already verified by a network scan."""
        ip = _normalise_ip(discovery_info[CONF_IP_ADDRESS])
        mac = discovery_info["mac"]

        if self._is_ip_configured(ip):
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Daikin {ip}", data={CONF_IP_ADDRESS: ip}
        )

    async def _async_add_entries(
        self, devices: list[DaikinDeviceInfo]
    ) -> AddEntriesResult:
        """Run the normal manual config flow for each discovered IP."""
        added: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []

        for device in devices:
            result: config_entries.ConfigFlowResult | None = None
            try:
                result = await self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_INTEGRATION_DISCOVERY},
                    data={CONF_IP_ADDRESS: device.ip, "mac": device.mac},
                )
                if result.get("type") == FlowResultType.CREATE_ENTRY:
                    added.append(device.ip)
                elif result.get("type") == FlowResultType.ABORT and result.get(
                    "reason"
                ) in {"already_configured", "already_in_progress"}:
                    skipped.append(device.ip)
                else:
                    failed.append(device.ip)
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Unable to add discovered Daikin adapter %s", device.ip
                )
                failed.append(device.ip)
            finally:
                flow_id = result.get("flow_id") if result is not None else None
                if flow_id is not None:
                    with suppress(UnknownFlow):
                        self.hass.config_entries.flow.async_abort(flow_id)

        return AddEntriesResult(
            added=tuple(added),
            skipped=tuple(skipped),
            failed=tuple(failed),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change the LAN adapter IP without removing the config entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        current_ip = entry.data.get(CONF_IP_ADDRESS, "")

        if user_input is not None:
            try:
                ip = _normalise_ip(user_input[CONF_IP_ADDRESS])
            except ValueError:
                errors[CONF_IP_ADDRESS] = "invalid_ip"
            else:
                if self._is_ip_configured(ip, exclude_entry_id=entry.entry_id):
                    return self.async_abort(reason="already_configured")

                device = await self._async_validate_device(ip, errors)
                if device is not None:
                    await self.async_set_unique_id(device.mac)
                    if uses_legacy_unique_id(entry.unique_id):
                        self._abort_if_unique_id_configured()
                    else:
                        self._abort_if_unique_id_mismatch(reason="wrong_device")

                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=device.mac,
                        data_updates={CONF_IP_ADDRESS: ip},
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(current_ip),
            errors=errors,
        )

    def _is_ip_configured(
        self, ip: str, exclude_entry_id: str | None = None
    ) -> bool:
        """Check both current data and legacy unique IDs for duplicates."""
        return any(
            entry.entry_id != exclude_entry_id
            and (
                entry.data.get(CONF_IP_ADDRESS) == ip
                or entry.unique_id == ip
            )
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        )

    def _is_unique_id_configured(
        self, unique_id: str, exclude_entry_id: str | None = None
    ) -> bool:
        """Check whether a stable adapter identity already has an entry."""
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, unique_id
        )
        return entry is not None and entry.entry_id != exclude_entry_id

    async def _async_validate_device(
        self, ip: str, errors: dict[str, str]
    ) -> DaikinDeviceInfo | None:
        """Validate that an address is a reachable supported Daikin adapter."""
        try:
            return await async_get_device_info(self.hass, ip)
        except DaikinConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Daikin adapter %s", ip)
            errors["base"] = "unknown"
        return None
