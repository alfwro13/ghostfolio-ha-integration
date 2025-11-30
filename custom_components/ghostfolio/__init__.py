"""The Ghostfolio integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed


from .api import GhostfolioAPI
from .const import (
    CONF_UPDATE_INTERVAL, 
    DEFAULT_UPDATE_INTERVAL, 
    CONF_SHOW_HOLDINGS,
    CONF_SHOW_WATCHLIST,
    DOMAIN
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ghostfolio from a config entry."""
    api = GhostfolioAPI(
        base_url=entry.data["base_url"],
        access_token=entry.data["access_token"],
        verify_ssl=entry.data.get("verify_ssl", True),
    )

    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    coordinator = GhostfolioDataUpdateCoordinator(hass, api, update_interval, entry)
    
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class GhostfolioDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Ghostfolio data."""

    def __init__(self, hass: HomeAssistant, api: GhostfolioAPI, update_interval_minutes: int, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes),
        )
        self.api = api
        self.entry = entry

    async def _async_update_data(self):
        """Fetch data from Ghostfolio API."""
        try:
            # 1. Fetch List of Accounts
            accounts_data = await self.api.get_accounts()
            accounts_list = accounts_data.get("accounts", [])
            
            # 2. Fetch Global Portfolio Performance
            global_performance = await self.api.get_portfolio_performance()
            
            # 3. Fetch Data per Account
            account_performances = {}
            holdings_by_account = {}
            watchlist_items = []
            
            # Check config options
            show_holdings = self.entry.data.get(CONF_SHOW_HOLDINGS, True)
            show_watchlist = self.entry.data.get(CONF_SHOW_WATCHLIST, True)

            for account in accounts_list:
                if account.get("isExcluded"):
                    continue
                    
                account_id = account["id"]
                
                # A. Fetch Performance
                try:
                    perf_data = await self.api.get_portfolio_performance(account_id=account_id)
                    account_performances[account_id] = perf_data
                except Exception as e:
                    _LOGGER.warning(f"Failed to fetch performance for account {account['name']}: {e}")

                # B. Fetch Holdings (if enabled)
                if show_holdings:
                    try:
                        # We fetch per account to ensure we know exactly which account the holding belongs to
                        holdings_data = await self.api.get_holdings(account_id=account_id)
                        # The API usually returns { "holdings": [...] }
                        holdings_by_account[account_id] = holdings_data.get("holdings", [])
                    except Exception as e:
                        _LOGGER.warning(f"Failed to fetch holdings for account {account['name']}: {e}")

            # 4. Fetch Watchlist (if enabled)
            if show_watchlist:
                try:
                    wl_response = await self.api.get_watchlist()
                    # Handle response being list or dict depending on API version
                    if isinstance(wl_response, list):
                        watchlist_items = wl_response
                    elif isinstance(wl_response, dict):
                        watchlist_items = wl_response.get("watchlist", []) or wl_response.get("items", [])
                except Exception as e:
                    _LOGGER.warning(f"Failed to fetch watchlist: {e}")

            return {
                "accounts": accounts_data,
                "global_performance": global_performance,
                "account_performances": account_performances,
                "account_holdings": holdings_by_account,
                "watchlist": watchlist_items
            }

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
