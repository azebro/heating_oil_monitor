# Heating Oil Monitor - Developer & Architecture Guide

**Version**: 1.0.0 | **HA Minimum**: 2023.1 | **License**: MIT

---

## Project Structure

```
heating_oil_monitor/
├── custom_components/heating_oil_monitor/
│   ├── __init__.py           # Entry point: setup, coordinator creation, service registration
│   ├── manifest.json         # HA integration metadata (domain, version, iot_class)
│   ├── config_flow.py        # ConfigFlow + OptionsFlow UI wizard (279 lines)
│   ├── const.py              # All constants, config keys, defaults, physics constants
│   ├── coordinator.py        # Central data coordinator - business logic hub (678 lines)
│   ├── geometry.py           # Horizontal cylinder volume calculation (35 lines)
│   ├── consumption.py        # Daily consumption tracking and analytics (160 lines)
│   ├── refill.py             # Refill detection and stabilization (72 lines)
│   ├── thermal.py            # Temperature compensation / normalization (23 lines)
│   ├── sensor.py             # 8 sensor entity classes (647 lines)
│   ├── services.yaml         # Service definitions (record_refill)
│   ├── strings.json          # UI strings and translations
│   └── translations/en.json  # English localization
├── tests/
│   ├── conftest.py           # Shared fixtures: mock_hass, make_coordinator, consumption_tracker
│   ├── test_geometry.py      # Volume calculation tests
│   ├── test_consumption.py   # Consumption tracker tests
│   ├── test_refill.py        # Refill stabilizer tests
│   ├── test_thermal.py       # Temperature normalization tests
│   ├── test_coordinator.py   # Coordinator pipeline, refill, serialization, derived values
│   ├── test_config_flow.py   # Config flow schema and class tests
│   └── test_sensor.py        # Sensor attributes, device_info, state classes
├── experimentation/
│   ├── kingspan_api.ipynb    # Kingspan Connect API exploration
│   └── kingspan_wsdl.xml     # Kingspan SOAP API schema
├── config/                   # Dev container HA instance config
├── .devcontainer/            # Docker dev container setup
├── DOCUMENTATION.md          # End-user documentation
└── Readme.md                 # Quick start guide
```

---

## Architecture

### Component Dependency Graph

```
__init__.py
    ├── const.py
    ├── coordinator.py
    │    ├── const.py
    │    ├── geometry.py
    │    ├── consumption.py
    │    ├── refill.py
    │    └── thermal.py
    │         └── const.py
    └── sensor.py
         ├── const.py
         └── coordinator.py (retrieves from hass.data)
```

### Data Flow Pipeline

```
Air Gap Sensor (state change)
    │
    ▼
coordinator._handle_air_gap_change()
    │
    ├── geometry.calculate_volume(air_gap, diameter, length) → raw_volume
    │
    ▼
coordinator._process_volume_reading(raw_volume)
    │
    ├── 1. Append to _reading_buffer (5-min window, max 2x buffer_size)
    │
    ├── 2. If no current volume → initialize from buffer median
    │
    ├── 3. If refill in progress → delegate to _handle_refill_stabilization()
    │
    ├── 4. If raw_change > refill_threshold → _start_refill_stabilization()
    │
    ├── 5. Debounce check (skip if < reading_debounce_seconds since last)
    │
    ├── 6. Median filter (last buffer_size readings)
    │
    ├── 7. Noise filter (ignore small positive changes)
    │
    ├── 8. If volume decreased ≥ 0.1L → record consumption
    │
    └── 9. _publish() → HeatingOilData snapshot → async_set_updated_data()
                                                        │
                                                        ▼
                                                   All sensors update
                                                   via CoordinatorEntity
```

### Refill Stabilization State Machine

```
MONITORING ──(volume increase > threshold)──► STABILIZING
    ▲                                              │
    │                                    add_reading() on each update
    │                                              │
    │                         ┌────────────────────┤
    │                         │                    │
    │              (time >= stabilization_minutes)  (5+ readings AND is_stable())
    │                         │                    │
    │                         ▼                    ▼
    └──────────────── _finalize_refill() ◄─────────┘
                          │
                          ├── stable_volume = median of last 5 readings
                          ├── refill_volume = stable - pre_refill
                          ├── _record_refill(stable_volume, refill_volume)
                          └── reset stabilizer
```

---

## Module Reference

### geometry.py

Single pure function. No state, no HA dependencies.

```python
calculate_volume(air_gap_cm: float, diameter_cm: float, length_cm: float) -> float
```

Uses circular segment area formula:

- `A = r² × arccos((r-h)/r) - (r-h) × √(2rh - h²)`
- `V = A × length / 1000` (cm³ → liters)

Edge cases: returns 0 if empty, `π×r²×L/1000` if full.

### thermal.py

Single pure function. Only dependency is `const.THERMAL_EXPANSION_COEFFICIENT`.

```python
normalize_volume(measured_volume: float, current_temp: float | None, reference_temp: float) -> float
```

Formula: `V_norm = V_measured / (1 + 0.00095 × (T_current - T_ref))`

Returns `measured_volume` unchanged if `current_temp` is None.

### consumption.py - ConsumptionTracker

Dataclass tracking daily consumption aggregates.

| Method                              | Description                             |
| ----------------------------------- | --------------------------------------- |
| `record(consumption, timestamp)`    | Add consumption; auto-prunes old data   |
| `get_daily_consumption(now)`        | Rolling average over `consumption_days` |
| `get_monthly_consumption(now)`      | Sum since 1st of current month          |
| `get_days_until_empty(now, volume)` | `volume / avg_daily` estimate           |
| `clear()`                           | Reset all history                       |
| `set_daily_totals(dict)`            | Restore from storage                    |
| `get_daily_totals()`                | Export for persistence                  |

Storage format: `dict[str, float]` mapping ISO date strings to daily liter totals.

### refill.py - RefillStabilizer

Dataclass managing the refill detection/stabilization lifecycle.

| Method                        | Description                                   |
| ----------------------------- | --------------------------------------------- |
| `start(volume, now, current)` | Enter stabilization; record pre-refill volume |
| `add_reading(volume, now)`    | Buffer a reading during stabilization         |
| `is_stable()`                 | True if last 5 readings' max-min ≤ threshold  |
| `should_finalize(now)`        | True if time limit reached OR stable early    |
| `stable_volume(fallback)`     | Median of last 5 buffered readings            |
| `reset()`                     | Clear all state                               |

### coordinator.py - HeatingOilCoordinator

Central hub extending `DataUpdateCoordinator[HeatingOilData]`.

**Constructor** wires up:

- State change listeners for air gap and temperature sensors
- `ConsumptionTracker`, `RefillStabilizer`, HA `Store`
- Initial volume/temperature from current sensor states
- Async history load from Store + recorder fallback
- Public `async_record_refill(volume)` method for the service handler

**Key internal state**:

- `_current_volume`, `_previous_volume`, `_current_temperature`
- `_last_refill_date`, `_last_refill_volume`, `_refill_history`
- `_reading_buffer`, `_last_processed_time`

**Persistence**: Uses `Store.async_delay_save()` with 10-second delay. Serializes consumption daily totals, refill history, and last refill info. Falls back to HA recorder for history restoration on fresh installs.

### sensor.py - Entity Classes

All sensors extend `CoordinatorEntity, RestoreEntity, SensorEntity`.

| Class                                    | Entity ID                 | Unit | State Class | Device Class |
| ---------------------------------------- | ------------------------- | ---- | ----------- | ------------ |
| `HeatingOilVolumeSensor`                 | `*_volume`                | L    | MEASUREMENT | VOLUME       |
| `HeatingOilNormalizedVolumeSensor`       | `*_normalized_volume`     | L    | TOTAL       | VOLUME       |
| `HeatingOilDailyConsumptionSensor`       | `*_daily_consumption`     | L    | MEASUREMENT | -            |
| `HeatingOilDailyConsumptionEnergySensor` | `*_daily_consumption_kwh` | kWh  | MEASUREMENT | -            |
| `HeatingOilMonthlyConsumptionSensor`     | `*_monthly_consumption`   | L    | TOTAL       | VOLUME       |
| `HeatingOilDaysUntilEmptySensor`         | `*_days_until_empty`      | days | -           | -            |
| `HeatingOilLastRefillSensor`             | `*_last_refill`           | -    | -           | TIMESTAMP    |
| `HeatingOilLastRefillVolumeSensor`       | `*_last_refill_volume`    | L    | TOTAL       | VOLUME       |

All sensors set `device_info` to group under a single "Heating Oil Tank" device, keyed by the air gap sensor entity ID.

### config_flow.py

Two flow classes sharing a `_build_schema(defaults)` helper:

- `HeatingOilMonitorConfigFlow` - Initial setup (validates sensor existence, sets unique_id)
- `HeatingOilMonitorOptionsFlow` - Post-setup reconfiguration (updates `entry.data`)

### **init**.py

- `async_setup()` - YAML legacy support, global service registration (`record_refill`)
- `async_setup_entry()` - Creates `HeatingOilCoordinator`, stores it in `hass.data[DOMAIN][entry_id]`, forwards to sensor platform
- `async_unload_entry()` - Cleanup
- `async_reload_entry()` - Triggered by options flow changes

The `record_refill` service calls `coordinator.async_record_refill(volume)` directly. An optional `entry_id` field targets a specific tank; if omitted, all coordinators are called.

---

## Configuration Parameters

| Key                                 | Type      | Default    | Unit  | Description                         |
| ----------------------------------- | --------- | ---------- | ----- | ----------------------------------- |
| `air_gap_sensor`                    | entity_id | (required) | -     | Ultrasonic distance sensor          |
| `tank_diameter_cm`                  | int       | (required) | cm    | Tank interior diameter              |
| `tank_length_cm`                    | int       | (required) | cm    | Tank interior length                |
| `refill_threshold_liters`           | int       | 100        | L     | Min increase to detect refill       |
| `noise_threshold_liters`            | float     | 2.0        | L     | Small volume fluctuations to ignore |
| `consumption_calculation_days`      | int       | 7          | days  | Rolling average window              |
| `temperature_sensor`                | entity_id | None       | -     | Optional temp sensor                |
| `reference_temperature`             | float     | 15.0       | C     | Normalization baseline              |
| `refill_stabilization_minutes`      | int       | 60         | min   | Max wait for stable readings        |
| `refill_stability_threshold_liters` | float     | 5.0        | L     | Max variance for stability          |
| `reading_buffer_size`               | int       | 5          | count | Median filter window                |
| `reading_debounce_seconds`          | int       | 60         | sec   | Min time between readings           |

---

## Physics Constants

| Constant                      | Value      | Source                        |
| ----------------------------- | ---------- | ----------------------------- |
| Kerosene energy density       | 10.0 kWh/L | Standard heating oil spec     |
| Thermal expansion coefficient | 0.00095 /C | Kerosene volumetric expansion |

---

## Service API

### `heating_oil_monitor.record_refill`

Manually record a tank refill event.

| Field      | Type   | Required | Description                                                            |
| ---------- | ------ | -------- | ---------------------------------------------------------------------- |
| `volume`   | float  | No       | Liters added. If omitted, marks refill at current volume.              |
| `entry_id` | string | No       | Target a specific tank config entry. If omitted, applies to all tanks. |

Implementation: `__init__.py` resolves the target coordinator(s) from `hass.data[DOMAIN]` and calls `coordinator.async_record_refill(volume)` directly.

---

## Data Persistence

### Store (primary)

- **Location**: `.storage/heating_oil_monitor_history_{entry_id}`
- **Contents**: consumption daily totals, refill history, last refill info
- **Write strategy**: Delayed save (10-second debounce via `async_delay_save`)
- **Read**: On coordinator init, async

### Recorder fallback

- **Trigger**: If Store data is missing/empty on startup
- **Method**: Reads up to 1000 historical volume sensor states from last 60 days
- **Purpose**: Recompute consumption from volume deltas for fresh installs

### State restoration

- Individual sensors restore via `RestoreEntity.async_get_last_state()`
- Volume, refill date, refill volume, days-until-empty are all restored

---

## Development

### Dev Container

The project includes a `.devcontainer/devcontainer.json` for VS Code Remote Containers with a Home Assistant development instance.

1. Open project in VS Code
2. "Reopen in Container"
3. F5 to start HA at `http://localhost:8123`
4. Integration auto-loads from `custom_components/`

### Running Tests

```bash
# From project root
pip install pytest homeassistant
pytest tests/ -v
```

Note: Tests require `homeassistant` package. Some tests use `pytest.importorskip("homeassistant")` to gracefully skip if unavailable.

### Adding a New Sensor

1. Create the sensor class in `sensor.py` extending `CoordinatorEntity, RestoreEntity, SensorEntity`
2. Add `device_info` using the shared `DeviceInfo(identifiers={(DOMAIN, coordinator.air_gap_sensor)}, ...)` pattern
3. Add the data field to `HeatingOilData` dataclass in `coordinator.py`
4. Populate the new field in `coordinator._publish()`
5. Add the sensor to the list in `_build_sensors()` in `sensor.py`
6. Add entity strings in `strings.json` and `translations/en.json`
7. Add tests

### Adding a New Config Parameter

1. Add `CONF_*` and `DEFAULT_*` constants in `const.py`
2. Add to schema in `_build_schema()` in `config_flow.py` (shared by both flows)
3. Add labels/descriptions in `strings.json` and `translations/en.json`
4. Accept in `HeatingOilCoordinator.__init__()` and wire through
5. Pass from `__init__.py:async_setup_entry()` config extraction
6. Add tests
