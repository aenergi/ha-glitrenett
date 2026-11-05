"""Sensors for Glitrenett Elbits."""

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinator import GlitrenettCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Glitrenett tariff sensor."""
    coordinator: GlitrenettCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GlitrenettTariffSensor(coordinator, entry)])


class GlitrenettTariffSensor(CoordinatorEntity[GlitrenettCoordinator], SensorEntity):
    """Expose the API tariff response as a sensor."""

    _attr_has_entity_name = True
    _attr_name = "Grid tariff"
    _attr_icon = "mdi:transmission-tower"

    def __init__(
        self, coordinator: GlitrenettCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the tariff sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = entry.entry_id

    @property
    def native_value(self) -> str:
        """Return the tariff title, or the number of tariffs returned."""
        collections: list[dict[str, Any]] = self.coordinator.data[
            "gridTariffCollections"
        ]
        if not collections:
            return "No tariff data"
        if len(collections) > 1:
            return f"{len(collections)} tariffs"
        grid_tariff = collections[0].get("gridTariff") or {}
        tariff_type = grid_tariff.get("tariffType") or {}
        return (
            tariff_type.get("title")
            or tariff_type.get("tariffKey")
            or "Grid tariff"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return tariff details from the API."""
        return {
            "grid_tariff_collections": self.coordinator.data[
                "gridTariffCollections"
            ]
        }
