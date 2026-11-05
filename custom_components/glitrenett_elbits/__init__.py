"""Glitrenett Elbits integration."""

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

DOMAIN = "glitrenett_elbits"
PLATFORMS = (Platform.SENSOR,)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Glitrenett Elbits from a config entry."""
    from .coordinator import GlitrenettCoordinator

    coordinator = GlitrenettCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Glitrenett Elbits config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id)
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True
