"""Sensors for Glitrenett."""

from datetime import datetime
from math import inf
from typing import Any, Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import DOMAIN
from .const import CONF_METERING_POINT_ID, SUBENTRY_METERING_POINT
from .coordinator import GlitrenettCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Glitrenett tariff sensors."""
    coordinator: GlitrenettCoordinator = hass.data[DOMAIN][entry.entry_id]
    for subentry in entry.get_subentries_of_type(SUBENTRY_METERING_POINT):
        async_add_entities(
            [
                GlitrenettSensor(coordinator, subentry, sensor)
                for sensor in (
                    "current_grid_price",
                    "three_hour_average",
                    "energy_level_price",
                    "energy_level",
                )
            ],
            config_subentry_id=subentry.subentry_id,
        )


class GlitrenettSensor(CoordinatorEntity[GlitrenettCoordinator], SensorEntity):
    """Expose a Glitrenett tariff or consumption value."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GlitrenettCoordinator, subentry: ConfigSubentry, sensor: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor = sensor
        self._point_id = subentry.data[CONF_METERING_POINT_ID]
        self._attr_unique_id = f"{self._point_id}_{sensor}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._point_id)},
            name=subentry.title,
            manufacturer="Glitrenett",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_translation_key = sensor
        self._attr_icon = (
            "mdi:transmission-tower"
            if sensor == "current_grid_price"
            else "mdi:flash"
        )
        if sensor == "current_grid_price":
            self._attr_native_unit_of_measurement = "NOK/kWh"
        elif sensor == "three_hour_average":
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        elif sensor == "energy_level_price":
            self._attr_native_unit_of_measurement = "NOK/month"
        self._cancel_tariff_change: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Set up tariff boundary updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_scheduled_tariff_change)
        self._schedule_next_tariff_change()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()
        self._schedule_next_tariff_change()

    @callback
    def _handle_tariff_change(self, _: datetime) -> None:
        """Update the current price when a tariff period expires."""
        self._cancel_tariff_change = None
        self.async_write_ha_state()
        self._schedule_next_tariff_change()

    @callback
    def _schedule_next_tariff_change(self) -> None:
        """Schedule an update for the next tariff period expiration."""
        self._cancel_scheduled_tariff_change()
        if self._sensor != "current_grid_price":
            return

        collection = self._collection()
        if collection is None:
            return
        grid_tariff = collection.get("gridTariff")
        tariff_price = (
            grid_tariff.get("tariffPrice") if isinstance(grid_tariff, dict) else None
        )
        hours = tariff_price.get("hours") if isinstance(tariff_price, dict) else None
        if not isinstance(hours, list):
            return

        now = dt_util.utcnow()
        next_expiration: datetime | None = None
        for hour in hours:
            if not isinstance(hour, dict):
                continue
            expiration = dt_util.parse_datetime(hour.get("expiredAt"))
            if expiration is None:
                continue
            expiration = dt_util.as_utc(expiration)
            if expiration <= now or (
                next_expiration is not None and expiration >= next_expiration
            ):
                continue
            next_expiration = expiration

        if next_expiration is not None:
            self._cancel_tariff_change = async_track_point_in_time(
                self.hass, self._handle_tariff_change, next_expiration
            )

    def _cancel_scheduled_tariff_change(self) -> None:
        """Cancel the scheduled tariff boundary update."""
        if self._cancel_tariff_change is not None:
            self._cancel_tariff_change()
            self._cancel_tariff_change = None

    @property
    def native_value(self) -> str | float | None:
        """Return the requested tariff or consumption value."""
        collection = self._collection()
        if collection is None:
            return None

        if self._sensor == "current_grid_price":
            return self._current_grid_price(collection)
        if self._sensor == "three_hour_average":
            return self._three_hour_average()

        level = self._current_energy_level(collection)
        if level is None:
            return None
        if self._sensor == "energy_level_price":
            value = level.get("monthlyTotal")
            return value if isinstance(value, (int, float)) else None
        value = level.get("levelInfo")
        return value if isinstance(value, str) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        collection = self._collection()
        if collection is None:
            return None
        if self._sensor == "energy_level":
            levels = self._price_levels(collection)
            if not levels:
                return None
            return {
                "energy_levels": [
                    {
                        "name": level.get("levelInfo"),
                        "min": level.get("valueMin"),
                        "max": level.get("valueMax"),
                        "price": level.get("monthlyTotal"),
                    }
                    for level in levels
                ]
            }
        if self._sensor == "current_grid_price":
            hours = self._tariff_hours(collection)
            if not hours:
                return None
            return {
                "grid_tariff_hours": [
                    {
                        "startTime": hour.get("startTime"),
                        "expiredAt": hour.get("expiredAt"),
                        "energyPrice": hour.get("energyPrice"),
                    }
                    for hour in hours
                ]
            }
        return None

    def _collection(self) -> dict[str, Any] | None:
        point_data = self.coordinator.data.get(self._point_id)
        if point_data is None:
            return None
        collection = point_data.get("collection")
        return collection if isinstance(collection, dict) else None

    @staticmethod
    def _current_grid_price(collection: dict[str, Any]) -> float | None:
        now = dt_util.utcnow()
        for hour in GlitrenettSensor._tariff_hours(collection):
            start = dt_util.parse_datetime(hour.get("startTime"))
            end = dt_util.parse_datetime(hour.get("expiredAt"))
            if start is None or end is None:
                continue
            if dt_util.as_utc(start) <= now < dt_util.as_utc(end):
                energy_price = hour.get("energyPrice")
                value = (
                    energy_price.get("total")
                    if isinstance(energy_price, dict)
                    else None
                )
                return value if isinstance(value, (int, float)) else None
        return None

    @staticmethod
    def _tariff_hours(collection: dict[str, Any]) -> list[dict[str, Any]]:
        """Return all hourly tariffs from the current tariff."""
        grid_tariff = collection.get("gridTariff")
        tariff_price = (
            grid_tariff.get("tariffPrice") if isinstance(grid_tariff, dict) else None
        )
        hours = tariff_price.get("hours") if isinstance(tariff_price, dict) else None
        if not isinstance(hours, list):
            return []
        return [hour for hour in hours if isinstance(hour, dict)]

    def _three_hour_average(self) -> float | None:
        point_data = self.coordinator.data.get(self._point_id)
        if point_data is None:
            return None
        value = point_data["point"].get("levelValue")
        return value if isinstance(value, (int, float)) else None

    @staticmethod
    def _price_levels(collection: dict[str, Any]) -> list[dict[str, Any]]:
        """Return all price levels from the current tariff."""
        grid_tariff = collection.get("gridTariff")
        tariff_price = (
            grid_tariff.get("tariffPrice") if isinstance(grid_tariff, dict) else None
        )
        price_info = (
            tariff_price.get("priceInfo")
            if isinstance(tariff_price, dict)
            else None
        )
        fixed_prices = (
            price_info.get("fixedPrices") if isinstance(price_info, dict) else None
        )
        if not isinstance(fixed_prices, list):
            return []

        levels: list[dict[str, Any]] = []
        for fixed_price in fixed_prices:
            if not isinstance(fixed_price, dict):
                continue
            price_levels = fixed_price.get("priceLevels")
            if not isinstance(price_levels, list):
                continue
            levels.extend(
                level for level in price_levels if isinstance(level, dict)
            )
        return levels

    def _current_energy_level(
        self, collection: dict[str, Any]
    ) -> dict[str, Any] | None:
        point_data = self.coordinator.data.get(self._point_id)
        if point_data is None:
            return None
        current_level = point_data["group"].get("currentFixedPriceLevel")
        if isinstance(current_level, dict) and current_level.get("levelId") is not None:
            grid_tariff = collection.get("gridTariff")
            tariff_price = (
                grid_tariff.get("tariffPrice") if isinstance(grid_tariff, dict) else None
            )
            price_info = (
                tariff_price.get("priceInfo") if isinstance(tariff_price, dict) else None
            )
            fixed_prices = (
                price_info.get("fixedPrices") if isinstance(price_info, dict) else None
            )
            if not isinstance(fixed_prices, list):
                return None
            for fixed_price in fixed_prices:
                if not isinstance(fixed_price, dict) or fixed_price.get(
                    "id"
                ) != current_level.get("id"):
                    continue
                price_levels = fixed_price.get("priceLevels")
                if not isinstance(price_levels, list):
                    return None
                return next(
                    (
                        level
                        for level in price_levels
                        if isinstance(level, dict)
                        and level.get("id") == current_level["levelId"]
                    ),
                    None,
                )
            return None

        consumption = self._three_hour_average()
        if consumption is None:
            return None

        for level in self._price_levels(collection):
            try:
                value_min = (
                    float(level["valueMin"])
                    if level.get("valueMin") is not None
                    else -inf
                )
                value_max = (
                    float(level["valueMax"])
                    if level.get("valueMax") is not None
                    else inf
                )
            except (TypeError, ValueError):
                continue
            if value_min <= consumption < value_max:
                return level
        return None
