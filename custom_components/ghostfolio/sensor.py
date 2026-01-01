"""Sensor platform for Ghostfolio integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import GhostfolioDataUpdateCoordinator
from .const import (
    CONF_PORTFOLIO_NAME,
    CONF_SHOW_TOTALS,
    CONF_SHOW_ACCOUNTS,
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
    """Set up Ghostfolio sensor platform."""
    coordinator = config_entry.runtime_data
    
    show_totals = config_entry.data.get(CONF_SHOW_TOTALS, True)
    show_accounts = config_entry.data.get(CONF_SHOW_ACCOUNTS, True)
    show_holdings = config_entry.data.get(CONF_SHOW_HOLDINGS, True)
    show_watchlist = config_entry.data.get(CONF_SHOW_WATCHLIST, True)

    known_ids: set[str] = set()

    # 1. Add Global Portfolio Sensors
    if show_totals:
        global_sensors = [
            GhostfolioCurrentValueSensor(coordinator, config_entry),
            GhostfolioNetPerformanceSensor(coordinator, config_entry),
            GhostfolioTimeWeightedReturnSensor(coordinator, config_entry),
            GhostfolioTotalInvestmentSensor(coordinator, config_entry),
            GhostfolioNetPerformanceWithCurrencySensor(coordinator, config_entry),
            GhostfolioTimeWeightedReturnFXSensor(coordinator, config_entry),
            GhostfolioSimpleGainPercentSensor(coordinator, config_entry),
        ]
        async_add_entities(global_sensors)
        for s in global_sensors:
            known_ids.add(s.unique_id)

    @callback
    def _update_sensors():
        """Check for new sensors (accounts, holdings, watchlist) and add them."""
        new_entities = []
        
        # --- ACCOUNTS & HOLDINGS ---
        accounts_data = coordinator.data.get("accounts", {}).get("accounts", [])

        for account in accounts_data:
            if account.get("isExcluded", False):
                continue

            account_id = account["id"]
            account_name = account["name"]

            # A. Add Per-Account Sensors
            if show_accounts:
                account_sensors = [
                    GhostfolioAccountValueSensor(coordinator, config_entry, account),
                    GhostfolioAccountCostSensor(coordinator, config_entry, account),
                    GhostfolioAccountPerformanceSensor(coordinator, config_entry, account),
                    GhostfolioAccountTWRSensor(coordinator, config_entry, account),
                    GhostfolioAccountSimpleGainSensor(coordinator, config_entry, account),
                ]
                
                for sens in account_sensors:
                    if sens.unique_id not in known_ids:
                        new_entities.append(sens)
                        known_ids.add(sens.unique_id)

            # B. Add Per-Holding Sensors
            if show_holdings:
                holdings_map = coordinator.data.get("account_holdings", {})
                holdings_list = holdings_map.get(account_id, [])

                for holding in holdings_list:
                    # Ensure valid holding with quantity
                    if float(holding.get("quantity") or 0) > 0:
                        symbol = holding.get("symbol")
                        safe_symbol = slugify(symbol)
                        unique_id = f"ghostfolio_holding_{account_id}_{safe_symbol}_{config_entry.entry_id}"
                        
                        if unique_id not in known_ids:
                            sensor = GhostfolioHoldingSensor(
                                coordinator, 
                                config_entry, 
                                account_id,   
                                account_name, 
                                holding
                            )
                            new_entities.append(sensor)
                            known_ids.add(unique_id)

        # --- WATCHLIST ---
        if show_watchlist:
            watchlist_items = coordinator.data.get("watchlist", [])
            for item in watchlist_items:
                symbol = item.get("symbol")
                safe_symbol = slugify(symbol)
                unique_id = f"ghostfolio_watchlist_{safe_symbol}_{config_entry.entry_id}"
                
                if unique_id not in known_ids:
                    sensor = GhostfolioWatchlistSensor(coordinator, config_entry, item)
                    new_entities.append(sensor)
                    known_ids.add(unique_id)

        if new_entities:
            async_add_entities(new_entities)

    config_entry.async_on_unload(coordinator.async_add_listener(_update_sensors))
    _update_sensors()


class GhostfolioBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Ghostfolio sensors."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")

        device_id = f"ghostfolio_portfolio_{config_entry.entry_id}"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"{self.portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Dynamically return the portfolio base currency."""
        if not self.coordinator.data:
            return "EUR"

        accounts_payload = self.coordinator.data.get("accounts", {})
        user_currency = accounts_payload.get("user", {}).get("baseCurrency")
        if user_currency:
            return user_currency

        if "baseCurrency" in accounts_payload:
            return accounts_payload["baseCurrency"]

        accounts_list = accounts_payload.get("accounts", [])
        if accounts_list and len(accounts_list) > 0:
            return accounts_list[0].get("currency", "EUR")

        return "EUR"

    @property
    def global_performance_data(self) -> dict[str, Any]:
        """Helper to get global performance data safely."""
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("global_performance", {}).get(
            "performance", {}
        )

    # --- HEALTH CHECKS ---

    def _is_provider_down(self, data_source: str | None) -> bool:
        """Check if a specific data source is down."""
        if not data_source:
            return False
        if not self.coordinator.data:
            return False
            
        providers = self.coordinator.data.get("providers", {})
        provider_info = providers.get(data_source)
        # If provider is tracked and inactive -> Down
        if provider_info and not provider_info.get("is_active", True):
            return True
        return False

    @property
    def is_portfolio_healthy(self) -> bool:
        """Return False if ANY active holding in the portfolio uses a down provider."""
        if not self.coordinator.data:
            return True
        
        all_holdings = self.coordinator.data.get("account_holdings", {})
        for holdings in all_holdings.values():
            for h in holdings:
                # Check active quantity
                if float(h.get("quantity") or 0) > 0:
                     if self._is_provider_down(h.get("dataSource")):
                         return False
        return True


# --- GLOBAL SENSORS ---

class GhostfolioCurrentValueSensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Value"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_current_value_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy:
            return None
        return self.global_performance_data.get("currentValueInBaseCurrency")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return {"current_net_worth": self.global_performance_data.get("currentNetWorth")}

class GhostfolioNetPerformanceSensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Gain"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy:
            return None
        return self.global_performance_data.get("netPerformance")

class GhostfolioTimeWeightedReturnSensor(GhostfolioBaseSensor):
    _attr_name = "Time-Weighted Return %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_percent_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy:
            return None
        percent_value = self.global_performance_data.get("netPerformancePercentage")
        return round(percent_value * 100, 2) if percent_value is not None else None

class GhostfolioTotalInvestmentSensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_total_investment_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy:
            return None
        return self.global_performance_data.get("totalInvestment")

class GhostfolioTimeWeightedReturnFXSensor(GhostfolioBaseSensor):
    _attr_name = "Time-Weighted Return FX %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_percent_with_currency_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy:
            return None
        percent_value = self.global_performance_data.get("netPerformancePercentageWithCurrencyEffect")
        return round(percent_value * 100, 2) if percent_value is not None else None

class GhostfolioNetPerformanceWithCurrencySensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Gain FX"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_with_currency_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy:
            return None
        return self.global_performance_data.get("netPerformanceWithCurrencyEffect")

class GhostfolioSimpleGainPercentSensor(GhostfolioBaseSensor):
    _attr_name = "Simple Gain %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_simple_gain_percent_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy:
            return None
        current_value = self.global_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.global_performance_data.get("totalInvestment")
        if current_value is None or total_investment is None or total_investment == 0:
            return None
        return round(((current_value - total_investment) / total_investment) * 100, 2)


# --- PER-ACCOUNT SENSORS ---

class GhostfolioAccountBaseSensor(GhostfolioBaseSensor):
    """Base class for Account-specific sensors."""

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry)
        self.account_id = account_data["id"]
        self.account_name = account_data["name"]
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_account_{self.account_id}_{config_entry.entry_id}")},
            "name": self.account_name, 
            "manufacturer": "Ghostfolio",
            "model": "Account Portfolio",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }

    @property
    def account_performance_data(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        performances = self.coordinator.data.get("account_performances", {})
        return performances.get(self.account_id, {}).get("performance", {})

    @property
    def is_account_healthy(self) -> bool:
        """Return False if ANY active holding in THIS account uses a down provider."""
        if not self.coordinator.data:
            return True

        all_holdings = self.coordinator.data.get("account_holdings", {})
        account_holdings = all_holdings.get(self.account_id, [])
        
        for h in account_holdings:
            if float(h.get("quantity") or 0) > 0:
                 if self._is_provider_down(h.get("dataSource")):
                     return False
        return True

class GhostfolioAccountValueSensor(GhostfolioAccountBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_value_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Value"

    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy:
            return None
        return self.account_performance_data.get("currentValueInBaseCurrency")

class GhostfolioAccountCostSensor(GhostfolioAccountBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_cost_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Cost"

    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy:
            return None
        return self.account_performance_data.get("totalInvestment")

class GhostfolioAccountPerformanceSensor(GhostfolioAccountBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_perf_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Gain"

    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy:
            return None
        return self.account_performance_data.get("netPerformance")

class GhostfolioAccountTWRSensor(GhostfolioAccountBaseSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_perf_pct_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Time-Weighted Return %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy:
            return None
        percent_value = self.account_performance_data.get("netPerformancePercentage")
        return round(percent_value * 100, 2) if percent_value is not None else None

class GhostfolioAccountSimpleGainSensor(GhostfolioAccountBaseSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_simple_gain_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Simple Gain %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy:
            return None
        current_value = self.account_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.account_performance_data.get("totalInvestment")
        if current_value is None or total_investment is None or total_investment == 0:
            return None
        return round(((current_value - total_investment) / total_investment) * 100, 2)


# --- PER-HOLDING SENSORS ---

class GhostfolioHoldingSensor(GhostfolioBaseSensor):
    """Sensor for a specific Asset/Holding."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_id, account_name, holding_data):
        super().__init__(coordinator, config_entry)
        self.account_id = account_id
        self.account_name = account_name
        self.symbol = holding_data.get("symbol")
        self.ticker_name = holding_data.get("name", self.symbol)

        # Unique ID
        safe_symbol = slugify(self.symbol)
        self._attr_unique_id = f"ghostfolio_holding_{self.account_id}_{safe_symbol}_{config_entry.entry_id}"

        # NAME FIXED: Just the Ticker Name (e.g. "Apple Inc.")
        self._attr_name = self.ticker_name

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_account_{self.account_id}_{config_entry.entry_id}")},
            "name": self.account_name, 
            "manufacturer": "Ghostfolio",
            "model": "Account Portfolio",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }

    @property
    def holding_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        holdings_map = self.coordinator.data.get("account_holdings", {})
        holdings_list = holdings_map.get(self.account_id, [])
        for h in holdings_list:
            if h.get("symbol") == self.symbol:
                return h
        return None

    @property
    def native_value(self) -> float | None:
        data = self.holding_data
        if not data:
            return None
            
        # --- Provider Check ---
        # If the holding's data source is reported as Down, return None (Unknown)
        if self._is_provider_down(data.get("dataSource")):
             return None
        # ----------------------

        return data.get("valueInBaseCurrency") or data.get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.holding_data
        if not data:
            return None

        # Currency Logic
        asset_currency = data.get("currency")
        base_currency = self.native_unit_of_measurement

        # Raw Values
        quantity = float(data.get("quantity") or 0)
        investment_in_base = float(data.get("investment") or 0)
        current_value_in_base = float(data.get("valueInBaseCurrency") or data.get("value") or 0)
        market_price_asset = float(data.get("marketPrice") or 0)

        # Calculations
        avg_buy_price_base = investment_in_base / quantity if quantity > 0 else 0
        market_price_base = current_value_in_base / quantity if quantity > 0 else 0
        gain_value_base = current_value_in_base - investment_in_base
        gain_pct = (gain_value_base / investment_in_base * 100) if investment_in_base > 0 else 0

        if market_price_base > avg_buy_price_base:
            trend = "up"
        elif market_price_base < avg_buy_price_base:
            trend = "down"
        else:
            trend = "break_even"

        return {
            "ticker": self.symbol,
            "account": self.account_name,
            "number_of_shares": quantity,
            "currency_asset": asset_currency,
            "currency_base": base_currency,
            "market_price": market_price_asset,
            "market_price_currency": asset_currency,
            "market_price_in_base_currency": round(market_price_base, 2),
            "average_buy_price": round(avg_buy_price_base, 2),
            "average_buy_price_currency": base_currency,
            "gain_value": round(gain_value_base, 2),
            "gain_value_currency": base_currency,
            "gain_pct": round(gain_pct, 2),
            "trend_vs_buy": trend,
            "asset_class": data.get("assetClass"),
            "data_source": data.get("dataSource"),
        }


# --- WATCHLIST SENSORS ---

class GhostfolioWatchlistSensor(GhostfolioBaseSensor):
    """Sensor for a Watchlist Item."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, item_data):
        super().__init__(coordinator, config_entry)
        self.symbol = item_data.get("symbol")
        self.data_source = item_data.get("dataSource")
        self.ticker_name = item_data.get("name", self.symbol)

        safe_symbol = slugify(self.symbol)
        self._attr_unique_id = f"ghostfolio_watchlist_{safe_symbol}_{config_entry.entry_id}"

        # NAME FIXED: Just the Ticker Name
        self._attr_name = self.ticker_name

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_account_watchlist_scope_{config_entry.entry_id}")},
            "name": "Watchlist", 
            "manufacturer": "Ghostfolio",
            "model": "Account Portfolio",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }

    @property
    def item_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        watchlist = self.coordinator.data.get("watchlist", [])
        for item in watchlist:
            if item.get("symbol") == self.symbol and item.get("dataSource") == self.data_source:
                return item
        return None

    @property
    def native_value(self) -> float | None:
        data = self.item_data
        if not data:
            return None
            
        # --- Provider Check ---
        if self._is_provider_down(self.data_source):
             return None
        # ----------------------

        return data.get("marketPrice")

    @property
    def native_unit_of_measurement(self) -> str | None:
        data = self.item_data
        if not data:
            return None
        return data.get("currency")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.item_data
        if not data:
            return None
        return {
            "ticker": self.symbol,
            "data_source": self.data_source,
            "asset_class": data.get("assetClass"),
            "market_price": data.get("marketPrice"),
            "currency": data.get("currency"),
            "trend_50d": data.get("trend50d"),
            "trend_200d": data.get("trend200d"),
            "market_change_24h": data.get("marketChange"),
            "market_change_pct_24h": data.get("marketChangePercentage"),
        }
