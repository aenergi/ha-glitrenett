"""Config flow for Glitrenett Elbits."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.update_coordinator import UpdateFailed

from . import DOMAIN
from .const import CONF_METERING_POINT_ID
from .coordinator import APIError, RequestThrottled, async_get_tariffs


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
            try:
                await async_get_tariffs(self.hass, api_key, metering_point_id)
            except APIError as err:
                error = "invalid_auth" if err.status in (401, 403) else "invalid_input"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_schema(),
                    errors={"base": error},
                )
            except RequestThrottled:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_schema(),
                    errors={"base": "request_throttled"},
                )
            except UpdateFailed:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_schema(),
                    errors={"base": "cannot_connect"},
                )
            return self.async_create_entry(
                title="Glitrenett Elbits",
                data={
                    CONF_API_KEY: api_key,
                    CONF_METERING_POINT_ID: metering_point_id,
                },
            )

        return self.async_show_form(step_id="user", data_schema=self._get_schema())

    async def async_step_reauth(self, _: dict[str, str] | None = None) -> FlowResult:
        """Handle reauthentication for an existing config entry."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Confirm an updated API key."""
        entry = self._reauth_entry
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                await async_get_tariffs(
                    self.hass, api_key, entry.data[CONF_METERING_POINT_ID]
                )
            except APIError as err:
                error = "invalid_auth" if err.status in (401, 403) else "invalid_input"
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=self._reauth_schema(),
                    errors={"base": error},
                )
            except RequestThrottled:
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=self._reauth_schema(),
                    errors={"base": "request_throttled"},
                )
            except UpdateFailed:
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=self._reauth_schema(),
                    errors={"base": "cannot_connect"},
                )
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_API_KEY: api_key}
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=self._reauth_schema()
        )

    @staticmethod
    def _get_schema() -> vol.Schema:
        """Return the configuration form schema."""
        return vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_METERING_POINT_ID): str,
            }
        )

    @staticmethod
    def _reauth_schema() -> vol.Schema:
        """Return the reauthentication form schema."""
        return vol.Schema({vol.Required(CONF_API_KEY): str})
