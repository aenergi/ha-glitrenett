"""Data update coordinator for Glitrenett Elbits."""

import asyncio
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import DOMAIN
from .const import CONF_METERING_POINT_ID

BASE_URL = "https://api.aenergi.no/Glitrenett/gridtariff/api/1"
UPDATE_INTERVAL = timedelta(hours=1)
_REQUEST_STATE_KEY = f"{DOMAIN}_request_states"


class APIError(Exception):
    """The API rejected the request."""

    def __init__(self, status: int) -> None:
        """Initialize the API error."""
        self.status = status


class RequestThrottled(Exception):
    """A request was suppressed to honor the hourly limit."""


@dataclass
class _RequestState:
    """Cached response and outbound request time for a metering point."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request: float | None = None
    data: dict[str, Any] | None = None
    api_key_fingerprint: bytes | None = None
    fingerprint_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))


def _get_request_state(hass: HomeAssistant, metering_point_id: str) -> _RequestState:
    """Return request state shared by config flows and coordinators."""
    states = hass.data.setdefault(_REQUEST_STATE_KEY, {})
    return states.setdefault(metering_point_id, _RequestState())


async def async_get_tariffs(
    hass: HomeAssistant, api_key: str, metering_point_id: str
) -> dict[str, Any]:
    """Fetch tariffs while enforcing the per-metering-point hourly request limit."""
    state = _get_request_state(hass, metering_point_id)
    api_key_fingerprint = hmac.digest(
        state.fingerprint_secret, api_key.encode(), "sha256"
    )
    async with state.lock:
        now = time.monotonic()
        if (
            state.last_request is not None
            and now - state.last_request < UPDATE_INTERVAL.total_seconds()
        ):
            if (
                state.data is not None
                and state.api_key_fingerprint == api_key_fingerprint
            ):
                return state.data
            raise RequestThrottled

        state.last_request = now
        try:
            async with async_get_clientsession(hass).post(
                f"{BASE_URL}/tariffquery/meteringpointsgridtariffs",
                headers={"X-API-Key": api_key},
                json={
                    "range": "today",
                    "meteringPointIds": [metering_point_id],
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if 400 <= response.status < 500:
                    raise APIError(response.status)
                if response.status == 304:
                    if (
                        state.data is None
                        or state.api_key_fingerprint != api_key_fingerprint
                    ):
                        raise UpdateFailed(
                            "Received not-modified without a cached tariff response"
                        )
                    return state.data
                if response.status == 204:
                    data = {"gridTariffCollections": []}
                else:
                    response.raise_for_status()
                    data = await response.json()
        except APIError:
            raise
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
        state.data = data
        state.api_key_fingerprint = api_key_fingerprint
        return data


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
        self._api_key = entry.data[CONF_API_KEY]
        self._metering_point_id = entry.data[CONF_METERING_POINT_ID]

    async def _async_update_data(self) -> dict[str, Any]:
        """Get today's grid tariffs for the configured metering point."""
        try:
            return await async_get_tariffs(
                self.hass, self._api_key, self._metering_point_id
            )
        except APIError as err:
            if err.status in (401, 403):
                raise ConfigEntryAuthFailed(
                    "Invalid Glitrenett API key"
                ) from err
            raise UpdateFailed(
                f"Glitrenett API returned HTTP {err.status}"
            ) from err
        except RequestThrottled as err:
            raise UpdateFailed(
                "A Glitrenett API request was recently made and no response is cached"
            ) from err
