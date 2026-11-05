"""Data update coordinator for Glitrenett Elbits."""

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import DOMAIN
from .config_flow import CONF_METERING_POINT_ID

BASE_URL = "https://api.aenergi.no/Glitrenett/gridtariff/api/1"
UPDATE_INTERVAL = timedelta(hours=1)


class GlitrenettCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch tariff data from the Glitrenett API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._session = async_get_clientsession(hass)
        self._api_key = entry.data[CONF_API_KEY]
        self._metering_point_id = entry.data[CONF_METERING_POINT_ID]

    async def _async_update_data(self) -> dict[str, Any]:
        """Get today's grid tariffs for the configured metering point."""
        try:
            async with self._session.post(
                f"{BASE_URL}/tariffquery/meteringpointsgridtariffs",
                headers={"X-API-Key": self._api_key},
                json={
                    "range": "today",
                    "meteringPointIds": [self._metering_point_id],
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status in (204, 304):
                    return {"gridTariffCollections": []}
                response.raise_for_status()
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed("Error communicating with Glitrenett API") from err
        except ValueError as err:
            raise UpdateFailed("Invalid response from Glitrenett API") from err

        if not isinstance(data, dict):
            raise UpdateFailed("Invalid response from Glitrenett API")
        collections = data.get("gridTariffCollections", [])
        if collections is None:
            collections = []
        if not isinstance(collections, list) or any(
            not isinstance(collection, dict) for collection in collections
        ):
            raise UpdateFailed("Invalid response from Glitrenett API")
        data["gridTariffCollections"] = collections
        return data
