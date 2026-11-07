"""Data update coordinator for Glitrenett."""

import asyncio
import hmac
import json
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
from homeassistant.util import dt as dt_util

from . import DOMAIN
from .const import CONF_METERING_POINT_ID, SUBENTRY_METERING_POINT

BASE_URL = "https://api.aenergi.no/Glitrenett/gridtariff/api/1"
UPDATE_INTERVAL = timedelta(hours=1)
_REQUEST_STATE_KEY = f"{DOMAIN}_request_states"
_LOGGER = logging.getLogger(__name__)


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

    last_request: float | None = None
    data: dict[str, Any] | None = None
    api_key_fingerprint: bytes | None = None
    last_request_failed: bool = False


@dataclass
class _RequestCache:
    """Coordinate requests and cache data across flows and coordinators."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    states: dict[str, _RequestState] = field(default_factory=dict)
    fingerprint_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))


def _index_metering_points(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Associate each metering point with its tariff and price-level group."""
    collections = data.get("gridTariffCollections")
    if collections is None:
        return {}
    if not isinstance(collections, list):
        raise UpdateFailed("Invalid grid tariff collections in API response")
    result: dict[str, dict[str, Any]] = {}
    for collection in collections:
        if not isinstance(collection, dict):
            raise UpdateFailed("Invalid grid tariff collection in API response")
        groups = collection.get("meteringPointsAndPriceLevels")
        if groups is None:
            continue
        if not isinstance(groups, list):
            raise UpdateFailed("Invalid metering point groups in API response")
        for group in groups:
            if not isinstance(group, dict):
                raise UpdateFailed("Invalid metering point group in API response")
            points = group.get("meteringPoints")
            if points is None:
                continue
            if not isinstance(points, list):
                raise UpdateFailed("Invalid metering points in API response")
            for point in points:
                if not isinstance(point, dict) or not isinstance(
                    point.get("meteringPointId"), str
                ):
                    raise UpdateFailed("Invalid metering point in API response")
                point_id = point["meteringPointId"]
                if point_id in result:
                    raise UpdateFailed("Duplicate metering point in API response")
                result[point_id] = {
                    "collection": collection,
                    "group": group,
                    "point": point,
                }
    return result


async def async_get_tariffs(
    hass: HomeAssistant, api_key: str, metering_point_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Fetch tariffs in batches, respecting the per-point hourly request limit."""
    if not metering_point_ids:
        return {}
    cache: _RequestCache = hass.data.setdefault(_REQUEST_STATE_KEY, _RequestCache())
    api_key_fingerprint = hmac.digest(
        cache.fingerprint_secret, api_key.encode(), "sha256"
    )
    async with cache.lock:
        now = time.monotonic()
        result: dict[str, dict[str, Any]] = {}
        to_fetch: list[str] = []
        for point_id in dict.fromkeys(metering_point_ids):
            state = cache.states.setdefault(point_id, _RequestState())
            if (
                state.last_request is not None
                and now - state.last_request < UPDATE_INTERVAL.total_seconds()
            ):
                if (
                    state.last_request_failed
                    or state.api_key_fingerprint != api_key_fingerprint
                ):
                    raise RequestThrottled
                if state.data is not None:
                    result[point_id] = state.data
            else:
                to_fetch.append(point_id)
        if not to_fetch:
            return result

        for point_id in to_fetch:
            cache.states[point_id].last_request = now
            cache.states[point_id].last_request_failed = True
        try:
            start_of_current_day = dt_util.start_of_local_day()
            end_of_next_day = start_of_current_day + timedelta(days=2) - timedelta(
                seconds=1
            )
            async with async_get_clientsession(hass).post(
                f"{BASE_URL}/tariffquery/meteringpointsgridtariffs",
                headers={"X-API-Key": api_key},
                json={
                    "startTime": start_of_current_day.isoformat(timespec="seconds"),
                    "endTime": end_of_next_day.isoformat(timespec="seconds"),
                    "meteringPointIds": to_fetch,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if 400 <= response.status < 500:
                    raise APIError(response.status)
                if response.status == 304:
                    if any(
                        cache.states[point_id].api_key_fingerprint
                        != api_key_fingerprint
                        for point_id in to_fetch
                    ):
                        raise UpdateFailed(
                            "Received not-modified without a cached tariff response"
                        )
                    indexed = {
                        point_id: cache.states[point_id].data
                        for point_id in to_fetch
                        if cache.states[point_id].data is not None
                    }
                elif response.status == 204:
                    data = {"gridTariffCollections": []}
                    indexed = _index_metering_points(data)
                else:
                    response.raise_for_status()
                    data = await response.json()
                    if not isinstance(data, dict):
                        raise UpdateFailed("Invalid response from Glitrenett API")
                    indexed = _index_metering_points(data)
                if response.status != 304:
                    _LOGGER.debug(
                        "Glitrenett API response: %s",
                        json.dumps(data, ensure_ascii=False, indent=2),
                    )
        except APIError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed("Error communicating with Glitrenett API") from err
        except ValueError as err:
            raise UpdateFailed("Invalid response from Glitrenett API") from err

        for point_id in to_fetch:
            state = cache.states[point_id]
            state.data = indexed.get(point_id)
            state.api_key_fingerprint = api_key_fingerprint
            state.last_request = time.monotonic()
            state.last_request_failed = False
            if state.data is not None:
                result[point_id] = state.data
        return result


class GlitrenettCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Fetch tariff data from the Glitrenett API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._api_key = entry.data[CONF_API_KEY]
        self._metering_point_ids = [
            subentry.data[CONF_METERING_POINT_ID]
            for subentry in entry.get_subentries_of_type(SUBENTRY_METERING_POINT)
        ]

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Get today's grid tariffs for configured metering points."""
        try:
            return await async_get_tariffs(
                self.hass, self._api_key, self._metering_point_ids
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
