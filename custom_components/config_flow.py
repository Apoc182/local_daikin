from homeassistant import config_entries
import voluptuous as vol

DOMAIN = "local_daikin"

class DaikinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            ip = user_input["ip_address"]
            await self.async_set_unique_id(ip)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"Daikin {ip}", data={"ip_address": ip})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("ip_address"): str}),
            errors=errors
        )