"""Binary sensor platform for Ghostfolio."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import EntityCategory

from . import GhostfolioDataUpdateCoordinator
from .const import DOMAIN, DATA_PROVIDERS, CONF_PORTFOLIO_NAME

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    
    entities = []
    
    # 1. Server Connectivity Sensor
    entities.append(GhostfolioServerSensor(coordinator, entry))

    # 2. Data Provider Sensors
    for provider in DATA_PROVIDERS:
        entities.append(GhostfolioProviderSensor(coordinator, entry, provider))
        
    async_add_entities(entities)

class GhostfolioServerSensor(CoordinatorEntity, BinarySensorEntity):
    """Sensor to check if Ghostfolio Server is reachable."""

    _attr_has_entity_name = True
    _attr_name = "Server"  # Will display as "Ghostfolio Server" in standard contexts
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry):
        """Initialize the server sensor."""
        super().__init__(coordinator)
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        self._attr_unique_id = f"ghostfolio_server_status_{config_entry.entry_id}"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}")},
            "name": f"{self.portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    @property
    def is_on(self) -> bool:
        """Return True if server is Connected."""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("server_online", False)


class GhostfolioProviderSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Data Provider Health Sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Custom translation for Available/Unavailable
    _attr_translation_key = "data_provider"

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry, provider_code: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.provider_code = provider_code
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        
        # Formatting name: "YAHOO" -> "Yahoo Status"
        nice_name = provider_code.replace("_", " ").title()
        self._attr_name = f"{nice_name} Status"
        self._attr_unique_id = f"ghostfolio_provider_{provider_code.lower()}_{config_entry.entry_id}"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}")},
            "name": f"{self.portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on (Available)."""
        if not self.coordinator.data:
            return None
        
        providers = self.coordinator.data.get("providers", {})
        data = providers.get(self.provider_code, {})
        return data.get("is_active", False)

    @property
    def extra_state_attributes(self):
        """Return attributes for diagnostics."""
        if not self.coordinator.data:
            return {}
        
        providers = self.coordinator.data.get("providers", {})
        data = providers.get(self.provider_code, {})
        return {
            "status_code": data.get("status_code"),
            "provider_code": self.provider_code
        }
