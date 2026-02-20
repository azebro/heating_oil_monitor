# Heating Oil Monitor - Code Review Report

**Date**: 2026-02-20
**Version Reviewed**: 1.0.0
**Reviewer**: Automated code review
**Scope**: Full codebase review - architecture, correctness, HA patterns, testing, security

---

## Executive Summary

This is a well-structured Home Assistant custom integration for monitoring heating oil in horizontal cylindrical tanks. The architecture follows HA conventions (ConfigFlow, DataUpdateCoordinator, RestoreEntity) and the domain logic is cleanly separated into focused modules. The main areas requiring attention are: **bugs in the coordinator**, **critically thin test coverage**, **duplicate code in sensor.py**, and **a few HA pattern violations**.

**Verdict**: Solid foundation, needs the bug fixes and test coverage before wider release.

---

## Critical Issues (Fix Before Release)

### BUG-1: `noise_threshold` units mismatch

**File**: `coordinator.py:367`

```python
if volume_change > 0 and abs(volume_change) < self.noise_threshold:
```

`noise_threshold` is configured in **centimeters** (`CONF_NOISE_THRESHOLD = "noise_threshold_cm"`, default 2 cm) but is compared against `volume_change` which is in **liters**. A 2 cm threshold means the filter silently discards volume increases under 2 _liters_, which may coincidentally be reasonable, but the semantic mismatch will cause confusion if a user sets it to 5 cm expecting 5 cm of air gap tolerance but actually filtering out 5 liters.

**Action**: Either convert the threshold to liters at comparison time (using the tank geometry), or rename the config parameter to liters and update the UI labels/descriptions.

### BUG-2: `@callback` on async methods

**File**: `coordinator.py:248-249`, `coordinator.py:262-263`, `coordinator.py:483-484`

```python
@callback
async def _handle_temperature_change(self, event: Event) -> None:
```

The `@callback` decorator tells HA the function is synchronous and safe to call without awaiting. Applying it to `async def` methods is contradictory. These methods use `await` internally (in `_handle_air_gap_change`'s call chain to `_process_volume_reading` which calls `_start_refill_stabilization` etc.). While HA's event system will still await them, the `@callback` decorator is misleading and may cause issues in future HA versions.

**Action**: Remove `@callback` from all three `async def` methods, or make them synchronous if no `await` is actually needed in the call path.

### BUG-3: Consumption cleared on every refill

**File**: `coordinator.py:472`

```python
self._consumption.clear()
```

On every refill (including manual refills), the entire consumption history is wiped. This destroys daily/monthly consumption data and makes `days_until_empty` return `None` until enough new data accumulates. For a refill mid-month, the monthly consumption sensor drops to 0.

**Action**: Do not clear consumption history on refill. Instead, consider adding a "last refill volume" baseline and continuing to track consumption from the new level.

### BUG-4: `_prune()` docstring says 60 days, `max_history_days` defaults to 365

**File**: `consumption.py:36`

```python
def _prune(self, now: datetime) -> None:
    """Keep only last 60 days of history."""
```

The docstring says 60 days but the actual implementation uses `self.max_history_days` which defaults to 365. Minor but misleading.

**Action**: Fix the docstring.

### BUG-5: Refill history serialization stores `datetime` objects directly

**File**: `coordinator.py:458-462`

```python
refill_record = {
    "timestamp": refill_date,  # datetime object
    ...
}
self._refill_history.append(refill_record)
```

Later in `_serialize_history()` (`coordinator.py:159`), `self._refill_history` is returned as-is. The HA `Store` class serializes to JSON, and `datetime` objects are not JSON-serializable. This will either silently fail or cause an error when the store tries to save.

Meanwhile, `_record_refill` at line 465 compares `entry["timestamp"] > cutoff` where `cutoff` is a `datetime` - this only works if the timestamps remain `datetime` objects (it would fail after deserialization where they'd be strings).

**Action**: Serialize timestamps to ISO strings when creating refill records, and deserialize them when loading from storage.

### BUG-6: Dead code - unused standard deviation calculation

**File**: `refill.py:55`

```python
_ = math.sqrt(variance)
```

This computes the standard deviation and discards it. The stability check uses `max_diff` instead.

**Action**: Remove the dead line.

---

## High Priority Issues

### HIGH-1: Test coverage is critically low

**Current state**: 5 test files, ~115 lines total. The coordinator test (`test_coordinator.py`) only verifies the class is importable. There are zero integration tests that exercise the full pipeline (sensor updates -> coordinator -> published data).

**Missing test coverage**:

- No tests for `config_flow.py` (0% coverage on 368 lines)
- No tests for `sensor.py` (0% coverage on 737 lines)
- No tests for `__init__.py` (0% coverage on 120 lines)
- No tests for the coordinator's processing pipeline, refill flow, debouncing, median filtering, or state persistence
- No tests for edge cases: negative air gaps, NaN/Inf sensor values, concurrent state changes

**Action**: Add at minimum:

1. Unit tests for coordinator's `_process_volume_reading` pipeline
2. Config flow tests (standard HA pattern using `MockConfigEntry`)
3. Sensor state restoration tests
4. Refill stabilization end-to-end test
5. History persistence round-trip test

### HIGH-2: Massive code duplication in sensor.py

**File**: `sensor.py:51-131` vs `sensor.py:133-203`

`async_setup_entry()` and `async_setup_platform()` are nearly identical - ~70 lines of duplicated config extraction and coordinator instantiation. The config-to-coordinator mapping is repeated verbatim.

**Action**: Extract a shared `_create_coordinator(hass, config)` helper and call it from both setup functions.

### HIGH-3: Further duplication in config_flow.py

**File**: `config_flow.py:68-178` vs `config_flow.py:215-361`

The schema definitions for the config flow and options flow are nearly identical (~150 duplicated lines). If a new config parameter is added, two places must be updated.

**Action**: Extract a `_build_schema(defaults: dict)` helper used by both flows.

### HIGH-4: No `device_info` on sensors - no device grouping

None of the sensor classes define `device_info`, so they appear as standalone entities in HA rather than being grouped under a single device. This is a standard HA pattern for custom integrations.

**Action**: Add a `device_info` property to a base class or mixin that groups all sensors under one device entry (e.g., "Oil Tank - {sensor_name}").

### HIGH-5: Shared `Store` key across multiple config entries

**File**: `coordinator.py:102`

```python
self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
```

`STORAGE_KEY` is `"heating_oil_monitor_history"` - a static string. If a user configures two tanks (two config entries), both coordinators write to the same storage file, corrupting each other's data.

**Action**: Include `entry.entry_id` in the storage key: `f"{STORAGE_KEY}_{entry_id}"`.

---

## Medium Priority Issues

### MED-1: `async_setup_entry` stores raw config in `hass.data` leaking into sensors

**File**: `__init__.py:96-97`

```python
config = {**entry.data, **entry.options}
hass.data[DOMAIN][entry.entry_id] = config
```

The coordinator should be the single source of truth. Currently, `sensor.py` reads config from `hass.data`, creates the coordinator, but never stores it back. Other parts of the system (e.g., service handlers, diagnostics) have no access to the coordinator instance.

**Action**: Store the coordinator in `hass.data[DOMAIN][entry.entry_id]` after creation, replacing the raw config dict.

### MED-2: Service registered globally but coordinator is per-entry

**File**: `__init__.py:59-76`

The `record_refill` service is registered in `async_setup()` (once globally) and fires a bus event. But if there are multiple config entries (multiple tanks), the event broadcasts to all coordinators. There's no way to target a specific tank.

**Action**: Either register the service per-entry with an `entity_id` or `entry_id` target field, or use HA's built-in entity service pattern.

### MED-3: `_reading_buffer` grows unbounded if timestamps are close

**File**: `coordinator.py:306-309`

```python
self._reading_buffer = [
    r for r in self._reading_buffer if r["timestamp"] > cutoff
][-max(buffer_size * 2, 10):]
```

The 5-minute window and `buffer_size * 2` cap mitigate growth, but if a sensor sends rapid updates (e.g., every second), the buffer could hold 300 entries before pruning. The list comprehension and slicing are O(n) on every reading.

**Action**: Cap the buffer to `buffer_size * 3` before filtering, or use a `deque(maxlen=...)`.

### MED-4: `state_changes_during_period` import pattern is fragile

**File**: `coordinator.py:617-618`

```python
from homeassistant.components.recorder.history import (
    state_changes_during_period,
)
```

This function was moved/renamed in HA 2023.6+. The import is inside a try/except so it won't crash, but it may silently fail to restore history on newer HA versions.

**Action**: Use `homeassistant.components.recorder.history.get_significant_states` or the newer recorder APIs depending on minimum supported HA version.

### MED-5: `HeatingOilMonthlyConsumptionSensor` uses `TOTAL_INCREASING` incorrectly

**File**: `sensor.py:409`

```python
self._attr_state_class = SensorStateClass.TOTAL_INCREASING
```

`TOTAL_INCREASING` expects the value to only increase within a period and reset on period change. The monthly consumption value resets to 0 at the start of each month, which is correct, but it also drops to 0 on every refill (because `consumption.clear()` is called). HA's long-term statistics (LTS) will treat each refill-induced zero as a "meter reset" and attempt to compensate.

**Action**: Use `SensorStateClass.TOTAL` instead, or stop clearing consumption on refill (see BUG-3).

### MED-6: `HeatingOilVolumeSensor` uses `SensorStateClass.TOTAL` incorrectly

**File**: `sensor.py:215`

```python
self._attr_state_class = SensorStateClass.TOTAL
```

`TOTAL` implies this is a cumulative/monotonic measurement (like total gas consumed). The oil volume is a gauge measurement (goes up on refill, down on consumption). HA's energy dashboard and LTS will misinterpret this.

**Action**: Use `SensorStateClass.MEASUREMENT` instead.

---

## Low Priority / Code Quality

### LOW-1: f-string in logging call

**File**: `__init__.py:62`

```python
_LOGGER.info(f"Manual refill recorded. Volume: {volume}")
```

Should use `%s` lazy formatting per HA guidelines: `_LOGGER.info("Manual refill recorded. Volume: %s", volume)`.

### LOW-2: `manifest.json` missing `integration_type`

For HA 2024.1+, custom integrations should specify `"integration_type": "hub"` or `"device"` in the manifest.

### LOW-3: No `conftest.py` or `pytest.ini` in test directory

Tests import `custom_components.heating_oil_monitor.*` directly but there's no sys.path setup. This works only if run from the project root with the right `PYTHONPATH`.

**Action**: Add a `conftest.py` with proper path setup and HA test fixtures.

### LOW-4: `async_setup_platform` receives `discovery_info` but YAML import uses config flow

**File**: `sensor.py:133-203`

The YAML import path in `__init__.py` triggers the config flow, which creates a config entry. The `async_setup_platform` (legacy) should never actually be called this way. This entire function may be dead code.

**Action**: Verify whether `async_setup_platform` is actually invoked. If not, remove it.

### LOW-5: `consumption.py` iterates daily totals multiple times

**File**: `consumption.py:66-100` and `consumption.py:116-160`

`get_daily_consumption()` and `get_days_until_empty()` both iterate `_daily_totals` twice (once to filter, once to find oldest). These could share a helper or use single-pass logic. Not a performance issue at ~365 entries max, but increases maintenance burden.

### LOW-6: No input validation on negative air gap or diameter

**File**: `geometry.py:8`

`calculate_volume` doesn't guard against `air_gap_cm < 0` or `diameter_cm <= 0`. While the config flow enforces min values, a malfunctioning sensor could send negative values.

**Action**: Add guards returning 0 for `air_gap_cm < 0` and the full-tank volume for `air_gap_cm < 0` (sensor below surface).

### LOW-7: Translations file only in English

Only `translations/en.json` exists. No issue for now, but worth noting for internationalization.

---

## Security Assessment

No security concerns identified. The integration:

- Has no external dependencies or network calls
- Does not handle user credentials
- Does not execute dynamic code
- Only reads sensor states and writes to HA's own storage
- Input validation is present in the config flow

---

## Summary Action Items

| Priority | ID     | Action                                       | Est. Effort |
| -------- | ------ | -------------------------------------------- | ----------- |
| Critical | BUG-1  | Fix noise_threshold units mismatch           | S           |
| Critical | BUG-2  | Remove @callback from async methods          | S           |
| Critical | BUG-3  | Stop clearing consumption history on refill  | M           |
| Critical | BUG-5  | Fix datetime serialization in refill history | M           |
| Critical | BUG-6  | Remove dead code in refill.py                | S           |
| High     | HIGH-1 | Add meaningful test coverage                 | L           |
| High     | HIGH-2 | Deduplicate sensor.py setup functions        | M           |
| High     | HIGH-3 | Deduplicate config_flow.py schemas           | M           |
| High     | HIGH-4 | Add device_info to sensors                   | M           |
| High     | HIGH-5 | Fix shared storage key for multi-entry       | S           |
| Medium   | MED-1  | Store coordinator in hass.data               | S           |
| Medium   | MED-2  | Fix service targeting for multi-tank         | M           |
| Medium   | MED-5  | Fix SensorStateClass on monthly sensor       | S           |
| Medium   | MED-6  | Fix SensorStateClass on volume sensor        | S           |
| Low      | BUG-4  | Fix docstring in consumption.py              | S           |
| Low      | LOW-1  | Fix f-string logging                         | S           |
| Low      | LOW-4  | Remove dead legacy setup_platform            | S           |
| Low      | LOW-6  | Add geometry input guards                    | S           |

**S** = Small (< 30 min), **M** = Medium (1-3 hours), **L** = Large (1+ day)

---

## What's Done Well

- **Clean module separation**: geometry, thermal, consumption, refill are all independently testable
- **Appropriate use of DataUpdateCoordinator**: central hub pattern is correct for this use case
- **RestoreEntity on all sensors**: state is recovered after HA restart
- **Dual persistence strategy**: both HA Store and recorder-based history restoration provide resilience
- **Comprehensive config flow**: all parameters are configurable with sensible defaults and UI descriptions
- **Median filtering and debouncing**: smart signal processing for noisy ultrasonic sensors
- **Frozen dataclass for HeatingOilData**: immutable snapshots prevent state corruption
- **Thorough existing documentation**: DOCUMENTATION.md is comprehensive with Mermaid diagrams and worked examples
