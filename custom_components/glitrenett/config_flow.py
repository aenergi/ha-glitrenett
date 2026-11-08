"""Config flow for Glitrenett."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentryData
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.update_coordinator import UpdateFailed

from . import DOMAIN
from .const import (
    CONF_METERING_POINT_ID,
    METERING_POINT_RANGES,
    SUBENTRY_METERING_POINT,
)
from .coordinator import APIError, RequestThrottled, async_get_tariffs

API_KEY_URL = "https://www.glitrenett.no/kunde/nettleie-og-priser/api-for-nettleiepriser"
CONF_ADD_ANOTHER = "add_another"


def _point_is_configured(hass: HomeAssistant, point_id: str) -> bool:
    """Check all entries for an existing metering point."""
    return any(
        subentry.unique_id == point_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        for subentry in entry.get_subentries_of_type(SUBENTRY_METERING_POINT)
    )


async def _validate_point(
    hass: HomeAssistant, api_key: str, point_id: str
) -> str | None:
    """Validate a metering point and return a flow error, if any."""
    if len(point_id) != 18 or not point_id.isascii() or not point_id.isdigit():
        return "invalid_metering_point_format"
    if not any(start <= point_id[:17] <= end for start, end in METERING_POINT_RANGES):
        return "metering_point_out_of_range"
    try:
        tariffs = await async_get_tariffs(hass, api_key, [point_id])
    except APIError as err:
        return "invalid_auth" if err.status in (401, 403) else "invalid_input"
    except RequestThrottled:
        return "request_throttled"
    except UpdateFailed:
        return "cannot_connect"
    if point_id not in tariffs:
        return "point_not_found"
    return None


def _point_schema(*, add_another: bool = False) -> vol.Schema:
    """Return a schema for a named metering point."""
    fields = {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_METERING_POINT_ID): str,
    }
    if add_another:
        fields[vol.Optional(CONF_ADD_ANOTHER, default=False)] = bool
    return vol.Schema(fields)


class GlitrenettConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Glitrenett."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the flow."""
        self._api_key = ""
        self._points: list[ConfigSubentryData] = []

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Support independently managed metering points."""
        return {SUBENTRY_METERING_POINT: GlitrenettMeteringPointFlow}

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Ask for the account API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_key = user_input[CONF_API_KEY].strip()
            if self._api_key:
                return await self.async_step_metering_point()
            errors["base"] = "invalid_input"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
            last_step=False,
        )

    async def async_step_metering_point(
        self, user_input: dict[str, str | bool] | None = None
    ) -> FlowResult:
        """Add one or more metering points before creating the account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input[CONF_NAME]).strip()
            point_id = str(user_input[CONF_METERING_POINT_ID]).strip()
            if not name or not point_id:
                errors["base"] = "invalid_input"
            elif _point_is_configured(self.hass, point_id) or any(
                point["unique_id"] == point_id for point in self._points
            ):
                errors["base"] = "already_configured"
            elif error := await _validate_point(self.hass, self._api_key, point_id):
                errors[
                    CONF_METERING_POINT_ID
                    if error in (
                        "invalid_metering_point_format",
                        "metering_point_out_of_range",
                    )
                    else "base"
                ] = error
            else:
                self._points.append(
                    {
                        "subentry_type": SUBENTRY_METERING_POINT,
                        "title": name,
                        "unique_id": point_id,
                        "data": {CONF_METERING_POINT_ID: point_id},
                    }
                )
                if user_input.get(CONF_ADD_ANOTHER):
                    return self.async_show_form(
                        step_id="metering_point",
                        data_schema=_point_schema(add_another=True),
                    )
                return self.async_create_entry(
                    title="Glitrenett",
                    data={CONF_API_KEY: self._api_key},
                    subentries=self._points,
                )
        return self.async_show_form(
            step_id="metering_point",
            data_schema=_point_schema(add_another=True),
            errors=errors,
        )

    async def async_step_reauth(self, _: dict[str, str] | None = None) -> FlowResult:
        """Handle reauthentication for an existing config entry."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Confirm an updated API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            points = self._reauth_entry.get_subentries_of_type(SUBENTRY_METERING_POINT)
            if not api_key:
                errors["base"] = "invalid_input"
            elif not points:
                errors["base"] = "no_metering_points"
            elif error := await _validate_point(
                self.hass, api_key, points[0].data[CONF_METERING_POINT_ID]
            ):
                errors["base"] = error
            else:
                changed = self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={**self._reauth_entry.data, CONF_API_KEY: api_key},
                )
                if not changed or not self._reauth_entry.update_listeners:
                    self.hass.config_entries.async_schedule_reload(
                        self._reauth_entry.entry_id
                    )
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )


class GlitrenettMeteringPointFlow(config_entries.ConfigSubentryFlow):
    """Add a metering point to an existing account."""

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Validate and add a metering point."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            point_id = user_input[CONF_METERING_POINT_ID].strip()
            if not name or not point_id:
                errors["base"] = "invalid_input"
            elif _point_is_configured(self.hass, point_id):
                errors["base"] = "already_configured"
            elif error := await _validate_point(
                self.hass, self._get_entry().data[CONF_API_KEY], point_id
            ):
                errors[
                    CONF_METERING_POINT_ID
                    if error in (
                        "invalid_metering_point_format",
                        "metering_point_out_of_range",
                    )
                    else "base"
                ] = error
            else:
                return self.async_create_entry(
                    title=name,
                    data={CONF_METERING_POINT_ID: point_id},
                    unique_id=point_id,
                )
        return self.async_show_form(
            step_id="user", data_schema=_point_schema(), errors=errors
        )
