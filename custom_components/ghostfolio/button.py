"""Button platform for Ghostfolio integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import EntityCategory

from . import GhostfolioDataUpdateCoordinator
from .const import DOMAIN, CONF_PORTFOLIO_NAME

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Ghostfolio button platform."""
    coordinator = entry.runtime_data
    
    async_add_entities([GhostfolioPruneButton(coordinator, entry)])

class GhostfolioPruneButton(CoordinatorEntity, ButtonEntity):
    """Button to prune orphaned entities."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "prune_orphans"

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry):
        """Initialize the button."""
        super().__init__(coordinator)
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        self._attr_unique_id = f"ghostfolio_prune_button_{config_entry.entry_id}"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}")},
            "name": f"{self.portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_prune_orphans()
