"""The Ghostfolio integration."""
from __future__ import annotations

import logging
import asyncio
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
    DOMAIN,
    DATA_PROVIDERS
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR]


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
        
        # Initialize default "Offline" data structure
        # If the API call fails, we return this so sensors show "Disconnected" or "Unknown"
        # rather than becoming completely Unavailable.
        data = {
            "server_online": False,
            "accounts": {},
            "global_performance": {},
            "account_performances": {},
            "account_holdings": {},
            "watchlist": [],
            "providers": {}
        }

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
                    raw_items = []
                    if isinstance(wl_response, list):
                        raw_items = wl_response
                    elif isinstance(wl_response, dict):
                        raw_items = wl_response.get("watchlist", []) or wl_response.get("items", [])
                    
                    # Enrich watchlist items with Market Data (Price & Currency)
                    for item in raw_items:
                        symbol = item.get("symbol")
                        data_source = item.get("dataSource")
                        
                        if symbol and data_source:
                            try:
                                market_data_resp = await self.api.get_market_data(data_source, symbol)
                                history = market_data_resp.get("marketData", [])
                                
                                if history and isinstance(history, list) and len(history) > 0:
                                    latest_idx = -1
                                    max_lookback = 5
                                    lookback_count = 0
                                    
                                    current_entry = history[latest_idx]
                                    current_price = float(current_entry.get("marketPrice") or 0)

                                    while lookback_count < max_lookback and abs(latest_idx) < len(history):
                                        prev_idx = latest_idx - 1
                                        prev_entry = history[prev_idx]
                                        prev_price = float(prev_entry.get("marketPrice") or 0)
                                        if current_price != prev_price:
                                            break
                                        latest_idx -= 1
                                        lookback_count += 1
                                        current_entry = history[latest_idx]

                                    if abs(latest_idx - 1) <= len(history):
                                        prev_entry = history[latest_idx - 1]
                                        prev_price = float(prev_entry.get("marketPrice") or 0)
                                        if prev_price > 0:
                                            change_val = current_price - prev_price
                                            change_pct = (change_val / prev_price) * 100
                                            item["marketChange"] = change_val
                                            item["marketChangePercentage"] = change_pct
                                    
                                    item["marketPrice"] = current_price
                                    item["marketDate"] = current_entry.get("date")
                                
                                profile = market_data_resp.get("assetProfile", {})
                                if not item.get("currency"):
                                    item["currency"] = profile.get("currency")
                                if not item.get("assetClass"):
                                    item["assetClass"] = profile.get("assetClass")
                                    
                            except Exception as err:
                                _LOGGER.debug(f"Failed to enrich watchlist item {symbol}: {err}")
                        
                        watchlist_items.append(item)
                        
                except Exception as e:
                    _LOGGER.warning(f"Failed to fetch watchlist: {e}")

            # 5. Fetch Provider Health (Parallel)
            provider_results = {}
            async def _fetch_health(code):
                return await self.api.get_provider_health(code)

            health_results = await asyncio.gather(*[_fetch_health(p) for p in DATA_PROVIDERS])
            for res in health_results:
                provider_results[res["code"]] = res

            # --- SUCCESS ---
            data["server_online"] = True
            data["accounts"] = accounts_data
            data["global_performance"] = global_performance
            data["account_performances"] = account_performances
            data["account_holdings"] = holdings_by_account
            data["watchlist"] = watchlist_items
            data["providers"] = provider_results
            
            return data

        except Exception as err:
            # We catch the error to keep the 'server' sensor alive (but Disconnected)
            # Other sensors will likely report Unknown/None because the data dicts are empty.
            _LOGGER.warning(f"Ghostfolio API update failed: {err}")
            return data
