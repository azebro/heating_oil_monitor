# Heating Oil Monitor - Home Assistant Integration

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

_Monitor heating oil consumption in horizontal cylindrical tanks with advanced temperature compensation._

---

## 🌟 Features

- **📊 Real-Time Volume Monitoring** - Accurate volume calculation using circular segment geometry
- **🌡️ Temperature Compensation** - Accounts for thermal expansion in outdoor tanks
- **📈 Consumption Tracking** - Daily, monthly, and historical consumption analytics
- **🔔 Smart Refill Detection** - Automatically detects tank refills
- **🔮 Predictive Analytics** - Estimates days until tank is empty
- **⚡ Energy Conversion** - Tracks consumption in both liters and kWh
- **💾 Data Persistence** - Restores consumption history from Home Assistant recorder

## 📋 Quick Start

### Prerequisites

- Home Assistant 2023.1 or newer
- Ultrasonic distance sensor measuring air gap (cm) from tank top to oil surface
- Horizontal cylindrical tank
- (Optional) Temperature sensor for outdoor installations

### Installation

1. Copy the `custom_components/heating_oil_monitor` directory to your Home Assistant's `custom_components` directory:

   ```
   config/
   └── custom_components/
       └── heating_oil_monitor/
   ```

2. Restart Home Assistant

3. Add the integration:
   - Go to **Settings** → **Devices & Services**
   - Click **+ Add Integration**
   - Search for "Heating Oil Monitor"
   - Follow the configuration wizard

### Basic Configuration

| Setting            | Description                   | Example                    |
| ------------------ | ----------------------------- | -------------------------- |
| **Air Gap Sensor** | Your ultrasonic sensor entity | `sensor.oil_tank_distance` |
| **Tank Diameter**  | Interior diameter             | `150` cm                   |
| **Tank Length**    | Interior length               | `200` cm                   |

**Optional settings**: Refill threshold, noise filtering, temperature sensor, refill stabilization, and reading filter options. See [full documentation](DOCUMENTATION.md) for all configuration options.

## 📊 Available Sensors

The integration creates 7-8 sensors (8th only with temperature sensor):

| Sensor                            | Description                                         |
| --------------------------------- | --------------------------------------------------- |
| **Heating Oil Volume**            | Current tank volume in liters                       |
| **Heating Oil Normalized Volume** | Temperature-compensated volume _(with temp sensor)_ |
| **Daily Consumption**             | Oil consumed today (liters)                         |
| **Daily Energy Consumption**      | Energy consumed today (kWh)                         |
| **Monthly Consumption**           | Oil consumed this month                             |
| **Days Until Empty**              | Estimated days remaining                            |
| **Last Refill**                   | Timestamp of last refill                            |
| **Last Refill Volume**            | Amount added in last refill                         |

## 🌡️ Temperature Compensation

For outdoor tanks, temperature changes cause oil to expand/contract (~0.095% per °C). This can create apparent volume changes of 10-40 liters that aren't actual consumption.

**With temperature compensation**, the integration:

- ✅ Distinguishes real consumption from thermal expansion
- ✅ Provides accurate fuel quantity independent of temperature
- ✅ Prevents false low-fuel warnings during cold weather
- ✅ Shows both measured and normalized volumes

**Example**: On a cold day (-5°C), a 1500L reading might normalize to 1529L, showing you have more fuel than the geometric measurement indicates (the oil has contracted).

## 📖 Full Documentation

**[→ Read the Complete Documentation](DOCUMENTATION.md)**

Includes:

- Detailed configuration guide
- Architecture diagrams (Mermaid)
- Volume calculation mathematics
- Temperature compensation theory
- Troubleshooting guide
- Advanced usage examples
- Integration with Energy Dashboard

## 🔧 Services

### heating_oil_monitor.record_refill

Manually record a refill event.

```yaml
service: heating_oil_monitor.record_refill
data:
  volume: 1500 # Liters added (optional)
```

## 📈 Example Automation

```yaml
automation:
  - alias: "Low Oil Alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.heating_oil_days_until_empty
        below: 7
    action:
      - service: notify.mobile_app
        data:
          message: "Only {{ states('sensor.heating_oil_days_until_empty') }} days of heating oil remaining!"
```

## 🛠️ Development Setup

### Prerequisites

- Docker Desktop
- Visual Studio Code with Dev Containers extension

### Getting Started

1. Clone this repository
2. Open in VS Code
3. Click "Reopen in Container" when prompted
4. Press F5 to start debugging

The integration will be automatically loaded in the development Home Assistant instance at `http://localhost:8123`

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Credits

Developed by [azebro](https://github.com/azebro) for the Home Assistant community.

---

**[📚 Full Documentation](DOCUMENTATION.md)** | **[🐛 Report Issues](https://github.com/azebro/heating_oil_monitor/issues)** | **[💬 Discussions](https://github.com/azebro/heating_oil_monitor/discussions)**

[releases-shield]: https://img.shields.io/github/release/azebro/heating_oil_monitor.svg?style=for-the-badge
[releases]: https://github.com/azebro/heating_oil_monitor/releases
[license-shield]: https://img.shields.io/github/license/azebro/heating_oil_monitor.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
