"""Number platform for Ghostfolio integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import GhostfolioDataUpdateCoordinator
from .const import (
    CONF_PORTFOLIO_NAME,
    CONF_SHOW_HOLDINGS,
    CONF_SHOW_WATCHLIST,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ghostfolio number platform."""
    coordinator = config_entry.runtime_data
    
    show_holdings = config_entry.data.get(CONF_SHOW_HOLDINGS, True)
    show_watchlist = config_entry.data.get(CONF_SHOW_WATCHLIST, True)

    known_ids: set[str] = set()

    @callback
    def _update_numbers():
        """Check for new holdings/watchlist items and create limit numbers."""
        new_entities = []
        
        # 1. Process Holdings
        if show_holdings:
            accounts_data = coordinator.data.get("accounts", {}).get("accounts", [])
            for account in accounts_data:
                if account.get("isExcluded", False):
                    continue

                account_id = account["id"]
                account_name = account["name"]
                holdings_map = coordinator.data.get("account_holdings", {})
                holdings_list = holdings_map.get(account_id, [])

                for holding in holdings_list:
                    if float(holding.get("quantity") or 0) > 0:
                        symbol = holding.get("symbol")
                        
                        # Create Low and High limit entities
                        for limit_type in ["low", "high"]:
                            unique_id = f"ghostfolio_limit_{limit_type}_{account_id}_{slugify(symbol)}_{config_entry.entry_id}"
                            
                            if unique_id not in known_ids:
                                new_entities.append(
                                    GhostfolioLimitNumber(
                                        coordinator, 
                                        config_entry, 
                                        symbol, 
                                        limit_type,
                                        unique_id,
                                        account_id=account_id,
                                        account_name=account_name
                                    )
                                )
                                known_ids.add(unique_id)

        # 2. Process Watchlist
        if show_watchlist:
            watchlist_items = coordinator.data.get("watchlist", [])
            for item in watchlist_items:
                symbol = item.get("symbol")
                for limit_type in ["low", "high"]:
                    unique_id = f"ghostfolio_watchlist_limit_{limit_type}_{slugify(symbol)}_{config_entry.entry_id}"
                    
                    if unique_id not in known_ids:
                        new_entities.append(
                            GhostfolioLimitNumber(
                                coordinator, 
                                config_entry, 
                                symbol, 
                                limit_type,
                                unique_id,
                                account_id="watchlist_scope",
                                account_name="Watchlist"
                            )
                        )
                        known_ids.add(unique_id)

        if new_entities:
            async_add_entities(new_entities)

    # Register listener to add numbers dynamically as data updates
    config_entry.async_on_unload(coordinator.async_add_listener(_update_numbers))
    _update_numbers()


class GhostfolioLimitNumber(CoordinatorEntity, RestoreNumber):
    """Number entity for setting High/Low limits."""

    _attr_has_entity_name = True
    _attr_mode = "box"

    def __init__(
        self, 
        coordinator, 
        config_entry, 
        symbol, 
        limit_type, 
        unique_id,
        account_id,
        account_name
    ):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_unique_id = unique_id
        
        # Store account name for the attribute
        self.account_name = account_name
        
        # Entity Name: "AAPL - Low Limit"
        self._attr_name = f"{symbol} - {limit_type.capitalize()} Limit"
        
        self._limit_type = limit_type
        self._attr_native_value = None
        
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        
        # Device Info: Create a device per Account
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_account_{account_id}_{config_entry.entry_id}")},
            "name": account_name, 
            "manufacturer": "Ghostfolio",
            "model": "Account Portfolio",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return entity specific state attributes."""
        return {
            "account": self.account_name,
        }

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_number_data()) is not None:
            self._attr_native_value = last_state.native_value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        self.async_write_ha_state()
