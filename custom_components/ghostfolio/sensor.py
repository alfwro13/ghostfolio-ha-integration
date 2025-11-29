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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import GhostfolioDataUpdateCoordinator
from .const import (
    CONF_PORTFOLIO_NAME,
    CONF_SHOW_TOTALS,
    CONF_SHOW_ACCOUNTS,
    CONF_SHOW_HOLDINGS,
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
    entities = []

    # Check configuration options (Default to True if not present for backward compatibility)
    show_totals = config_entry.data.get(CONF_SHOW_TOTALS, True)
    show_accounts = config_entry.data.get(CONF_SHOW_ACCOUNTS, True)
    show_holdings = config_entry.data.get(CONF_SHOW_HOLDINGS, True)

    # 1. Add Global Portfolio Sensors
    if show_totals:
        entities.extend(
            [
                GhostfolioCurrentValueSensor(coordinator, config_entry),
                GhostfolioNetPerformanceSensor(coordinator, config_entry),
                GhostfolioTimeWeightedReturnSensor(coordinator, config_entry),
                GhostfolioTotalInvestmentSensor(coordinator, config_entry),
                GhostfolioNetPerformanceWithCurrencySensor(coordinator, config_entry),
                GhostfolioTimeWeightedReturnFXSensor(coordinator, config_entry),
                GhostfolioSimpleGainPercentSensor(coordinator, config_entry),
            ]
        )

    # 2. Iterate Accounts for Account & Holding Sensors
    accounts_data = coordinator.data.get("accounts", {}).get("accounts", [])

    for account in accounts_data:
        # Skip excluded/hidden accounts
        if account.get("isExcluded", False):
            continue

        # Add Per-Account Sensors
        if show_accounts:
            entities.append(
                GhostfolioAccountValueSensor(coordinator, config_entry, account)
            )
            entities.append(
                GhostfolioAccountCostSensor(coordinator, config_entry, account)
            )
            entities.append(
                GhostfolioAccountPerformanceSensor(coordinator, config_entry, account)
            )
            entities.append(
                GhostfolioAccountTWRSensor(coordinator, config_entry, account)
            )
            entities.append(
                GhostfolioAccountSimpleGainSensor(coordinator, config_entry, account)
            )

        # Add Per-Holding Sensors
        if show_holdings:
            account_id = account["id"]
            # Look up holdings specifically for this account
            holdings_map = coordinator.data.get("account_holdings", {})
            holdings_list = holdings_map.get(account_id, [])

            for holding in holdings_list:
                # Ensure valid holding with quantity
                if float(holding.get("quantity", 0)) > 0:
                    entities.append(
                        GhostfolioHoldingSensor(
                            coordinator, config_entry, account, holding
                        )
                    )

    if entities:
        async_add_entities(entities)


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

        # 1. Try User Settings
        user_currency = accounts_payload.get("user", {}).get("baseCurrency")
        if user_currency:
            return user_currency

        # 2. Try root level
        if "baseCurrency" in accounts_payload:
            return accounts_payload["baseCurrency"]

        # 3. Fallback to first account currency
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


# --- GLOBAL SENSORS ---


class GhostfolioCurrentValueSensor(GhostfolioBaseSensor):
    """Sensor for current portfolio value."""

    _attr_name = "Portfolio Value"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_current_value_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("currentValueInBaseCurrency")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return {
            "current_net_worth": self.global_performance_data.get("currentNetWorth"),
        }


class GhostfolioNetPerformanceSensor(GhostfolioBaseSensor):
    """Sensor for net performance (Absolute Gain)."""

    _attr_name = "Portfolio Gain"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("netPerformance")


class GhostfolioTimeWeightedReturnSensor(GhostfolioBaseSensor):
    """Sensor for Time Weighted Return (Ghostfolio standard)."""

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
        percent_value = self.global_performance_data.get("netPerformancePercentage")
        return percent_value * 100 if percent_value is not None else None


class GhostfolioTotalInvestmentSensor(GhostfolioBaseSensor):
    """Sensor for total investment."""

    _attr_name = "Portfolio Cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_total_investment_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("totalInvestment")


class GhostfolioTimeWeightedReturnFXSensor(GhostfolioBaseSensor):
    """Sensor for TWR with FX effect."""

    _attr_name = "Time-Weighted Return FX %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = (
            f"ghostfolio_net_performance_percent_with_currency_{config_entry.entry_id}"
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        percent_value = self.global_performance_data.get(
            "netPerformancePercentageWithCurrencyEffect"
        )
        return percent_value * 100 if percent_value is not None else None


class GhostfolioNetPerformanceWithCurrencySensor(GhostfolioBaseSensor):
    """Sensor for net performance with currency effect (Absolute)."""

    _attr_name = "Portfolio Gain FX"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = (
            f"ghostfolio_net_performance_with_currency_{config_entry.entry_id}"
        )

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("netPerformanceWithCurrencyEffect")


class GhostfolioSimpleGainPercentSensor(GhostfolioBaseSensor):
    """Sensor for simple gain percentage (Money-Weighted proxy)."""

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
        current_value = self.global_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.global_performance_data.get("totalInvestment")

        if current_value is None or total_investment is None or total_investment == 0:
            return None

        return ((current_value - total_investment) / total_investment) * 100


# --- PER-ACCOUNT SENSORS ---


class GhostfolioAccountBaseSensor(GhostfolioBaseSensor):
    """Base class for Account-specific sensors."""

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry)
        self.account_id = account_data["id"]
        self.account_name = account_data["name"]

    @property
    def account_performance_data(self) -> dict[str, Any]:
        """Get performance data specifically for this account."""
        if not self.coordinator.data:
            return {}

        performances = self.coordinator.data.get("account_performances", {})
        return performances.get(self.account_id, {}).get("performance", {})


class GhostfolioAccountValueSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Value."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_value_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Value"

    @property
    def native_value(self) -> float | None:
        return self.account_performance_data.get("currentValueInBaseCurrency")


class GhostfolioAccountCostSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Cost (Total Investment)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_cost_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Cost"

    @property
    def native_value(self) -> float | None:
        return self.account_performance_data.get("totalInvestment")


class GhostfolioAccountPerformanceSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Performance (Absolute Gain)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_perf_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Gain"

    @property
    def native_value(self) -> float | None:
        return self.account_performance_data.get("netPerformance")


class GhostfolioAccountTWRSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account TWR (Ghostfolio default)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_perf_pct_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Time-Weighted Return %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        percent_value = self.account_performance_data.get("netPerformancePercentage")
        return percent_value * 100 if percent_value is not None else None


class GhostfolioAccountSimpleGainSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Simple Gain %."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_simple_gain_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Simple Gain %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        current_value = self.account_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.account_performance_data.get("totalInvestment")

        if current_value is None or total_investment is None or total_investment == 0:
            return None

        return ((current_value - total_investment) / total_investment) * 100


# --- PER-HOLDING SENSORS (FIXED) ---


class GhostfolioHoldingSensor(GhostfolioBaseSensor):
    """Sensor for a specific Asset/Holding."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data, holding_data):
        super().__init__(coordinator, config_entry)
        self.account_id = account_data["id"]
        self.account_name = account_data["name"]
        self.symbol = holding_data.get("symbol")
        self.ticker_name = holding_data.get("name", self.symbol)

        # Unique ID
        safe_symbol = slugify(self.symbol)
        self._attr_unique_id = f"ghostfolio_holding_{self.account_id}_{safe_symbol}_{config_entry.entry_id}"

        self._attr_name = f"{self.account_name} - {self.ticker_name}"

    @property
    def holding_data(self) -> dict[str, Any] | None:
        """Find the latest data for this holding."""
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
        """State is the Total Value (Market Value in Base Currency)."""
        data = self.holding_data
        if not data:
            return None
        return data.get("valueInBaseCurrency") or data.get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return detailed attributes with currency clarity."""
        data = self.holding_data
        if not data:
            return None

        # 1. Identify Currencies
        asset_currency = data.get("currency")
        base_currency = self.native_unit_of_measurement  # e.g., GBP

        # 2. Extract Raw Values
        quantity = float(data.get("quantity") or 0)
        investment_in_base = float(data.get("investment", 0))  # Total Cost (Base)
        current_value_in_base = float(
            data.get("valueInBaseCurrency") or data.get("value", 0)
        )
        market_price_asset = float(
            data.get("marketPrice", 0)
        )  # Price in Asset Currency

        # 3. Calculate Derived Values (Base Currency)

        # Average Buy Price (Base)
        avg_buy_price_base = investment_in_base / quantity if quantity > 0 else 0

        # Market Price (Base) -> Derived from Total Value / Quantity
        market_price_base = current_value_in_base / quantity if quantity > 0 else 0

        # Gain (Base)
        gain_value_base = current_value_in_base - investment_in_base
        gain_pct = (
            (gain_value_base / investment_in_base * 100) if investment_in_base > 0 else 0
        )

        # 4. Trend Calculation (Base vs Base comparison)
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
            # --- Currencies ---
            "currency_asset": asset_currency,
            "currency_base": base_currency,
            # --- Prices (Asset Currency) ---
            "market_price": market_price_asset,
            "market_price_currency": asset_currency,
            # --- Prices (Base Currency - Comparable) ---
            "market_price_in_base_currency": round(market_price_base, 2),
            "average_buy_price": round(avg_buy_price_base, 2),
            "average_buy_price_currency": base_currency,
            # --- Gains (Base Currency) ---
            "gain_value": round(gain_value_base, 2),
            "gain_value_currency": base_currency,
            "gain_pct": round(gain_pct, 2),
            # --- Analysis ---
            "trend_vs_buy": trend,
            "asset_class": data.get("assetClass"),
        }
