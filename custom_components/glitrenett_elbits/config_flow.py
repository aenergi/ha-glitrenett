"""Config flow for Glitrenett Elbits."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.data_entry_flow import FlowResult

from . import DOMAIN

CONF_METERING_POINT_ID = "metering_point_id"


class GlitrenettConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Glitrenett Elbits."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Set up the integration."""
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            metering_point_id = user_input[CONF_METERING_POINT_ID].strip()
            if not api_key or not metering_point_id:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_schema(),
                    errors={"base": "invalid_input"},
                )
            await self.async_set_unique_id(metering_point_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Glitrenett Elbits",
                data={
                    CONF_API_KEY: api_key,
                    CONF_METERING_POINT_ID: metering_point_id,
                },
            )

        return self.async_show_form(step_id="user", data_schema=self._get_schema())

    @staticmethod
    def _get_schema() -> vol.Schema:
        """Return the configuration form schema."""
        return vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_METERING_POINT_ID): str,
            }
        )
