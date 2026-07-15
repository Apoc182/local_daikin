"""Config flow for Local Daikin."""

from __future__ import annotations

import ipaddress
from typing import Any

from homeassistant import config_entries
import voluptuous as vol

from .const import CONF_IP_ADDRESS, DOMAIN


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
        """Add a Daikin LAN adapter from the Home Assistant UI."""
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
            step_id="user",
            data_schema=_schema(),
            errors=errors,
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
