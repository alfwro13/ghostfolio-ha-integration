<div align="center">
   <img src="https://brands.home-assistant.io/ghostfolio/icon.png" alt="Ghostfolio Logo" width="120" height="120">
</div>

# Ghostfolio Home Assistant Integration

A Home Assistant Custom Component (HACS integration) for monitoring your [Ghostfolio](https://github.com/ghostfolio/ghostfolio) portfolio performance. This integration works with any Ghostfolio instance, but if you prefer an all-in-one solution, you can run Ghostfolio directly on your server using the [Home Assistant Add-on](https://github.com/alfwro13/ha-addon-ghostfolio).

## Features

This integration automatically detects your portfolio's base currency and offers granular tracking options:
- **Global Totals:** Track overall portfolio value and performance.
- **Account Breakdowns:** Individual sensors for each investment account.
- **Asset Tracking:** Dedicated sensors for every holding and watchlist item.
- **Price Alerts:** Configurable High/Low limit numbers for every asset to trigger automations.
- **Diagnostic Sensors:** Monitor the connection status of your Ghostfolio server and its data providers.
- **Smart Health Checks:** Automatically detects if a data provider (e.g., Yahoo Finance) is down and marks affected sensors as `Unknown` instead of reporting erroneous zero values.
- **Entity Cleanup:** Built-in tool to remove old or sold assets from Home Assistant.

### 1. Global Portfolio Sensors
- **Portfolio Value**: The current total market value of your portfolio.
- **Portfolio Cost**: The total amount of money you have invested.
- **Portfolio Gain**: The absolute net performance (Value - Cost).
- **Portfolio Gain FX**: The absolute net performance including currency effects.
- **Simple Gain %**: The simple percentage return, calculated as `(Value - Cost) / Cost`.
- **Time-Weighted Return %**: The Time-Weighted Rate of Return (TWR) of your portfolio (measures strategy performance, ignoring deposits/withdrawals).
- **Time-Weighted Return FX %**: The TWR percentage including currency effects.

*Note: If any active holding in your portfolio relies on a data provider that is currently down, these global summary sensors will report `Unknown` to prevent misleading data.*

### 2. Per-Account Sensors
Sensors are created for each of your Ghostfolio accounts (excluding hidden ones):
- **[Account Name] Value**: Current market value of the specific account.
- **[Account Name] Cost**: Total investment in the specific account.
- **[Account Name] Gain**: Absolute gain/loss for the specific account.
- **[Account Name] Simple Gain %**: Simple percentage gain/loss for the specific account.
- **[Account Name] Time-Weighted Return %**: Time-Weighted Return percentage for the specific account.

### 2. Per-Account Sensors
Sensors are created for each of your Ghostfolio accounts (excluding hidden ones):
- **[Account Name] Value**: Current market value of the specific account.
- **[Account Name] Cost**: Total investment in the specific account.
- **[Account Name] Gain**: Absolute gain/loss for the specific account.
- **[Account Name] Simple Gain %**: Simple percentage gain/loss for the specific account.
- **[Account Name] Time-Weighted Return %**: Time-Weighted Return percentage for the specific account.

### 3. Per-Holding Sensors (Assets)
Track every individual asset in your portfolio with a dedicated sensor:
- **Sensor State**: Total market value of the holding in your base currency.
- **Friendly Name**: The ticker symbol (e.g., "AAPL", "VWRL.AS").
- **Attributes**: 
  - `market_price`, `average_buy_price`, `number_of_shares`
  - `gain_value`, `gain_pct`, `trend_vs_buy`
  - `low_limit_set`, `low_limit_reached`
  - `high_limit_set`, `high_limit_reached`

*Note: If the data provider for a specific holding is down, its sensor will report `Unknown`.*

### 4. Watchlist Sensors
Track items from your Ghostfolio Watchlist even if you don't own them yet.
- **Sensor State**: Current market price.
- **Friendly Name**: The ticker symbol (e.g., "TSLA").
- **Attributes**: 
  - `market_change_24h`, `market_change_pct_24h`
  - `trend_50d`, `trend_200d`
  - `low_limit_set`, `low_limit_reached`
  - `high_limit_set`, `high_limit_reached`
*(Requires "Show Watchlist Items" to be enabled in configuration)*

### 5. Price Limit Configuration (Inputs)
For every Holding and Watchlist item, the integration creates two **Number** entities that allow you to set price targets directly from Home Assistant.

- **[Ticker] - Low Limit**
- **[Ticker] - High Limit**

When you set a value in these number entities, the corresponding main Sensor (Holding or Watchlist) immediately updates its attributes:
- **`low_limit_set` / `high_limit_set`**: Displays the limit value you set (or `false` if not set).
- **`low_limit_reached`**: Becomes `true` if the value drops to or below your limit.
- **`high_limit_reached`**: Becomes `true` if the value rises to or above your limit.

### 6. Using Price Alerts in Automations
Because the alert logic is built directly into the sensors, you can create a single, powerful automation to handle notifications for ALL your assets at once, without needing to reference the number entities.

**Example Automation:**
Trigger when *any* Ghostfolio sensor's `low_limit_reached` attribute turns true.

```yaml
alias: "Ghostfolio - Low Limit Alert"
trigger:
  - platform: state
    entity_id:
      - sensor.watchlist_apple_inc
      - sensor.isa_tesla_inc
      # Add your sensors here or use a template/group
    attribute: low_limit_reached
    to: true
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "Price Alert: {{ trigger.to_state.attributes.friendly_name }}"
      message: "{{ trigger.to_state.attributes.friendly_name }} has dropped below your limit of {{ trigger.to_state.attributes.low_limit_set }}. Current value: {{ trigger.to_state.state }} {{ trigger.to_state.attributes.currency_base }}"
```

### 7. Advanced: Group Automation
If you have many assets, listing every sensor in an automation trigger can be tedious. A more efficient approach is to create a **Group Helper** in Home Assistant.

1. Create a new **Group** (Sensor Group) in Home Assistant settings and add all your Ghostfolio holding sensors to it.
2. Use the following automation to monitor the entire group. This automation triggers whenever *any* member of the group changes state, checks which entity caused the change using `last_entity_id`, and sends a notification if that specific asset has reached its limit.

```yaml
alias: Ghostfolio Group Low Limit Notification
description: >-
  Monitors the Ghostfolio Holdings group and sends a notification when
  any member reaches its set low limit.
triggers:
  - trigger: state
    entity_id:
      - sensor.ghostfolio_holdings_group
    attribute: last_entity_id
conditions:
  - condition: template
    value_template: >
      {{ state_attr(trigger.to_state.attributes.last_entity_id, 'low_limit_reached') == true }}
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: >-
        Account: {{ state_attr(trigger.to_state.attributes.last_entity_id, 'account') }}
        
        {{ state_attr(trigger.to_state.attributes.last_entity_id, 'friendly_name') }}
        has hit the low limit of: 
        {{ state_attr(trigger.to_state.attributes.last_entity_id, 'low_limit_set') }} 
        {{ state_attr(trigger.to_state.attributes.last_entity_id, 'unit_of_measurement') }}
mode: single
```

### 8. Diagnostic Sensors & Tools
To help you troubleshoot issues and maintain your setup, the integration provides diagnostic entities. You can find these on the main Portfolio Device page in Home Assistant.

- **Ghostfolio Server**: Indicates if your Ghostfolio instance is reachable (`Connected` / `Disconnected`).
- **Data Provider Status**: Individual sensors for each data provider (e.g., `Yahoo Status`, `Coingecko Status`) showing if they are `Available` or `Unavailable`.
- **Prune Orphaned Entities**: A button that, when pressed, scans your Home Assistant registry and removes any Ghostfolio entities (such as sold assets or removed watchlist items) that are no longer returned by the API.

## Installation

### HACS (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed.
2. Add this repository as a custom repository in HACS:
   - Go to HACS → Integrations.
   - Click the three dots in the top right corner.
   - Select "Custom repositories".
   - Add this repository URL and select "Integration" as the category.
3. Install the integration from HACS.
4. Restart Home Assistant.

### Manual Installation

1. Download the latest release.
2. Copy the `custom_components/ghostfolio` folder to your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services**.
2. Click **Add Integration** and search for **"Ghostfolio"**.
3. Enter your details and choose which sensors to create:
   - **Base URL**: The URL of your Ghostfolio instance (e.g., `https://your-ghostfolio.com`).
   - **Access Token**: Your Ghostfolio access token.
   - **Show Portfolio Totals**: (Optional) Check to create global portfolio sensors.
   - **Show Individual Accounts**: (Optional) Check to create sensors for each account.
   - **Show Holdings**: (Optional) Check to create sensors and limit numbers for individual assets.
   - **Show Watchlist Items**: (Optional) Check to create sensors and limit numbers for watchlist items.

### Getting Your Access Token

1. Log in to your Ghostfolio instance.
2. Go to **Settings > Security**.
3. Scroll to **Security Token**.
4. Generate or copy your access token (Anonymous Access).

## API Endpoints Used

This integration uses the following Ghostfolio API endpoints:

- `POST /api/v1/auth/anonymous`: For authentication.
- `GET /api/v1/account`: For retrieving the account list and base currency settings.
- `GET /api/v2/portfolio/performance`: For retrieving global and per-account performance data.
- `GET /api/v1/portfolio/holdings`: For retrieving individual asset details.
- `GET /api/v1/watchlist`: For retrieving watchlist items.
- `GET /api/v1/market-data`: For fetching real-time price and history for watchlist items.
- `GET /api/v1/health/data-provider/{provider}`: For checking the status of data providers.

## Data Update Frequency

The integration updates portfolio data every **15 minutes** by default. This can be customized in the configuration options.

## Support

For issues with this integration, please open an issue on the GitHub repository.

For issues with Ghostfolio itself, please refer to the [Ghostfolio GitHub repository](https://github.com/ghostfolio/ghostfolio).

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments
This integration is maintained by @alfwro13.
Originally based on the [ha_ghostfolio repository by MichelFR](https://github.com/MichelFR/ha_ghostfolio). It has since been significantly expanded to include granular per-holding tracking, per-account sensors, dynamic configuration options, diagnostic tools, and improved currency handling.
