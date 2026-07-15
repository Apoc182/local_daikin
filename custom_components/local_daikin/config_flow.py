"""Config flow for Local Daikin."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_USER
import voluptuous as vol

from .const import CONF_IP_ADDRESS, DOMAIN
from .scanner import async_scan_network, get_default_network, parse_network

CONF_NETWORK = "network"
_LOGGER = logging.getLogger(__name__)


def _normalise_ip(value: str) -> str:
    """Return a canonical IP address or raise ValueError."""
    return str(ipaddress.ip_address(value.strip()))


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

                # Keep the existing IP-based unique ID for compatibility with
                # entries created by earlier releases of this integration.
                await self.async_set_unique_id(ip)
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
                    new_ips = [
                        ip
                        for ip in discovered
                        if not self._is_ip_configured(ip)
                    ]
                    if not new_ips:
                        return self.async_abort(reason="no_new_devices")

                    added = await self._async_add_entries(new_ips)
                    if added:
                        return self.async_abort(reason="scan_complete")
                    errors["base"] = "scan_failed"

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {vol.Required(CONF_NETWORK, default=default_network): str}
            ),
            errors=errors,
        )

    async def _async_add_entries(self, ips: list[str]) -> bool:
        """Run the normal manual config flow for each discovered IP."""
        added = False
        for ip in ips:
            flow = await self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_USER},
            )
            flow_id = flow.get("flow_id")
            if not flow_id:
                continue

            menu_result = await self.hass.config_entries.flow.async_configure(
                flow_id,
                {"next_step_id": "manual"},
            )
            if not menu_result.get("flow_id"):
                continue

            result = await self.hass.config_entries.flow.async_configure(
                flow_id,
                {CONF_IP_ADDRESS: ip},
            )
            if result.get("type") == "create_entry":
                added = True
        return added

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

                # Older releases used the address as the config entry unique
                # ID. It must move with the address when a user edits it.
                self.hass.config_entries.async_update_entry(entry, unique_id=ip)
                return self.async_update_reload_and_abort(
                    entry,
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
