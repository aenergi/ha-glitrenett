"""Sensors for Glitrenett Elbits."""

from math import inf
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import dt as dt_util
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinator import GlitrenettCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Glitrenett tariff sensors."""
    coordinator: GlitrenettCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GlitrenettSensor(coordinator, entry, "current_grid_price"),
            GlitrenettSensor(coordinator, entry, "three_hour_average"),
            GlitrenettSensor(coordinator, entry, "energy_level_price"),
            GlitrenettSensor(coordinator, entry, "energy_level"),
        ]
    )


class GlitrenettSensor(CoordinatorEntity[GlitrenettCoordinator], SensorEntity):
    """Expose a Glitrenett tariff or consumption value."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GlitrenettCoordinator, entry: ConfigEntry, sensor: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor = sensor
        self._attr_unique_id = f"{entry.entry_id}_{sensor}"
        self._attr_name = {
            "current_grid_price": "Current energy grid price",
            "three_hour_average": "Top three hours average consumption",
            "energy_level_price": "Current energy level price",
            "energy_level": "Current energy level",
        }[sensor]
        self._attr_icon = (
            "mdi:transmission-tower"
            if sensor == "current_grid_price"
            else "mdi:flash"
        )
        if sensor == "current_grid_price":
            self._attr_native_unit_of_measurement = "NOK/kWh"
        elif sensor == "three_hour_average":
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self) -> str | float | None:
        """Return the requested tariff or consumption value."""
        collection = self._collection()
        if collection is None:
            return None

        if self._sensor == "current_grid_price":
            return self._current_grid_price(collection)
        if self._sensor == "three_hour_average":
            return self._three_hour_average(collection)

        level = self._current_energy_level(collection)
        if level is None:
            return None
        if self._sensor == "energy_level_price":
            value = level.get("monthlyTotal")
            return value if isinstance(value, (int, float)) else None
        value = level.get("levelInfo")
        return value if isinstance(value, str) else None

    def _collection(self) -> dict[str, Any] | None:
        collections = self.coordinator.data.get("gridTariffCollections")
        if not isinstance(collections, list) or not collections:
            return None
        collection = collections[0]
        return collection if isinstance(collection, dict) else None

    @staticmethod
    def _current_grid_price(collection: dict[str, Any]) -> float | None:
        grid_tariff = collection.get("gridTariff")
        tariff_price = (
            grid_tariff.get("tariffPrice") if isinstance(grid_tariff, dict) else None
        )
        hours = tariff_price.get("hours") if isinstance(tariff_price, dict) else None
        if not isinstance(hours, list):
            return None

        now = dt_util.utcnow()
        for hour in hours:
            if not isinstance(hour, dict):
                continue
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
    def _three_hour_average(collection: dict[str, Any]) -> float | None:
        metering_data = collection.get("meteringPointsAndPriceLevels")
        points = (
            metering_data.get("meteringPoints")
            if isinstance(metering_data, dict)
            else None
        )
        if (
            not isinstance(points, list)
            or not points
            or not isinstance(points[0], dict)
        ):
            return None
        value = points[0].get("levelValue")
        return value if isinstance(value, (int, float)) else None

    def _current_energy_level(
        self, collection: dict[str, Any]
    ) -> dict[str, Any] | None:
        consumption = self._three_hour_average(collection)
        if consumption is None:
            return None
        price_info = collection.get("priceInfo")
        fixed_prices = (
            price_info.get("fixedPrices") if isinstance(price_info, dict) else None
        )
        levels = (
            fixed_prices.get("priceLevels")
            if isinstance(fixed_prices, dict)
            else None
        )
        if not isinstance(levels, list):
            return None

        for level in levels:
            if not isinstance(level, dict):
                continue
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
            if value_min < consumption < value_max:
                return level
        return None
