"""Tests for the HeatingOilCoordinator processing pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.util import dt as dt_util

from custom_components.heating_oil_monitor.coordinator import (
    HeatingOilCoordinator,
    HeatingOilData,
)
from custom_components.heating_oil_monitor.const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_READING_BUFFER_SIZE,
    DEFAULT_READING_DEBOUNCE_SECONDS,
    DEFAULT_REFILL_STABILIZATION_MINUTES,
    DEFAULT_REFILL_STABILITY_THRESHOLD,
    KEROSENE_KWH_PER_LITER,
)
from conftest import make_coordinator


def test_coordinator_importable() -> None:
    assert HeatingOilCoordinator is not None


# ---------------------------------------------------------------------------
# Construction and initialization
# ---------------------------------------------------------------------------

class TestCoordinatorInit:
    """Tests for coordinator construction and initialization."""

    def test_coordinator_creates_with_defaults(self, mock_hass):
        """Coordinator should be instantiable with mocked hass."""
        coord = make_coordinator(mock_hass)
        assert coord is not None
        assert coord.air_gap_sensor == "sensor.air_gap"
        assert coord.tank_diameter == 124.0
        assert coord.tank_length == 180.0

    def test_coordinator_stores_parameters(self, mock_hass):
        """All constructor parameters should be stored."""
        coord = make_coordinator(
            mock_hass,
            refill_threshold=200,
            noise_threshold=5.0,
            consumption_days=14,
            reading_buffer_size=7,
            reading_debounce_seconds=120,
        )
        assert coord.refill_threshold == 200
        assert coord.noise_threshold == 5.0
        assert coord.consumption_days == 14
        assert coord.reading_buffer_size == 7
        assert coord.reading_debounce_seconds == 120

    def test_coordinator_initial_volume_from_sensor(self, mock_hass):
        """Coordinator should initialize volume from current sensor state."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        assert coord._current_volume is not None
        assert coord._current_volume > 0

    def test_coordinator_initial_volume_none_when_no_sensor(self, mock_hass):
        """Coordinator volume should be None when sensor has no state."""
        coord = make_coordinator(mock_hass)
        assert coord._current_volume is None

    def test_coordinator_publishes_initial_data(self, mock_hass):
        """Coordinator should publish data during initialization."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        assert coord.data is not None
        assert isinstance(coord.data, HeatingOilData)
        assert coord.data.volume is not None


# ---------------------------------------------------------------------------
# Volume processing pipeline
# ---------------------------------------------------------------------------

class TestProcessVolumeReading:
    """Tests for _process_volume_reading pipeline."""

    @pytest.mark.asyncio
    async def test_first_reading_sets_volume(self, mock_hass):
        """First reading should set initial volume."""
        coord = make_coordinator(mock_hass)
        assert coord._current_volume is None

        await coord._process_volume_reading(500.0)
        assert coord._current_volume == 500.0
        assert coord._previous_volume == 500.0

    @pytest.mark.asyncio
    async def test_consumption_decreases_volume(self, mock_hass):
        """A decrease below refill threshold should be recorded as consumption."""
        coord = make_coordinator(
            mock_hass,
            noise_threshold=0.5,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(500.0)
        initial = coord._current_volume

        await coord._process_volume_reading(490.0)
        assert coord._current_volume == 490.0
        assert coord._current_volume < initial

    @pytest.mark.asyncio
    async def test_noise_threshold_filters_small_increases(self, mock_hass):
        """Small volume increases below noise threshold should be ignored."""
        coord = make_coordinator(
            mock_hass,
            noise_threshold=3.0,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(500.0)

        # Small increase (1 L) - below noise threshold (3 L)
        await coord._process_volume_reading(501.0)
        assert coord._current_volume == 500.0  # Unchanged

    @pytest.mark.asyncio
    async def test_large_increase_triggers_refill(self, mock_hass):
        """Volume increase above refill threshold should trigger refill stabilization."""
        coord = make_coordinator(
            mock_hass,
            refill_threshold=50,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(500.0)

        await coord._process_volume_reading(700.0)
        assert coord._refill.in_progress is True

    @pytest.mark.asyncio
    async def test_debouncing_skips_rapid_readings(self, mock_hass):
        """Readings within debounce window should be buffered but not processed."""
        coord = make_coordinator(
            mock_hass,
            reading_debounce_seconds=60,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(500.0)

        await coord._process_volume_reading(490.0)
        assert len(coord._reading_buffer) >= 1

    @pytest.mark.asyncio
    async def test_median_filter_smooths_outliers(self, mock_hass):
        """Median filter should smooth out outlier readings."""
        coord = make_coordinator(
            mock_hass,
            reading_buffer_size=5,
            reading_debounce_seconds=0,
            noise_threshold=0.1,
        )
        await coord._process_volume_reading(500.0)

        # Add readings including an outlier
        readings = [498.0, 499.0, 450.0, 498.5, 499.5]
        for r in readings:
            coord._reading_buffer.append(
                {"timestamp": dt_util.now(), "volume": r}
            )

        median = coord._get_median_volume(coord._reading_buffer[-5:])
        assert 498.0 <= median <= 499.5

    @pytest.mark.asyncio
    async def test_buffer_pruning_caps_size(self, mock_hass):
        """Reading buffer should be pruned to prevent unbounded growth."""
        coord = make_coordinator(
            mock_hass,
            reading_buffer_size=3,
            reading_debounce_seconds=0,
        )
        for i in range(50):
            coord._reading_buffer.append(
                {"timestamp": dt_util.now(), "volume": 500.0 - i * 0.1}
            )

        await coord._process_volume_reading(490.0)
        assert len(coord._reading_buffer) <= 11

    @pytest.mark.asyncio
    async def test_consumption_records_to_tracker(self, mock_hass):
        """Consumption events should be recorded in the consumption tracker."""
        coord = make_coordinator(
            mock_hass,
            noise_threshold=0.1,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(500.0)
        await coord._process_volume_reading(490.0)

        daily = coord._consumption.get_daily_totals()
        assert len(daily) > 0
        total = sum(daily.values())
        assert abs(total - 10.0) < 0.1

    @pytest.mark.asyncio
    async def test_very_small_decrease_ignored(self, mock_hass):
        """Decreases smaller than 0.1 L should be ignored."""
        coord = make_coordinator(
            mock_hass,
            noise_threshold=0.1,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(500.0)
        await coord._process_volume_reading(499.95)
        assert coord._current_volume == 500.0


# ---------------------------------------------------------------------------
# Refill detection and stabilization
# ---------------------------------------------------------------------------

class TestRefillStabilization:
    """Tests for refill detection and stabilization in the coordinator."""

    @pytest.mark.asyncio
    async def test_refill_starts_stabilization(self, mock_hass):
        """Large volume increase should start refill stabilization."""
        coord = make_coordinator(
            mock_hass,
            refill_threshold=50,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(400.0)
        pre_refill = coord._current_volume

        await coord._process_volume_reading(700.0)
        assert coord._refill.in_progress is True
        assert coord._refill.pre_refill_volume == pre_refill

    @pytest.mark.asyncio
    async def test_refill_finalized_after_stabilization(self, mock_hass):
        """Refill should be finalized after stabilization period."""
        coord = make_coordinator(
            mock_hass,
            refill_threshold=50,
            refill_stabilization_minutes=1,
            refill_stability_threshold=5.0,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(400.0)

        await coord._process_volume_reading(700.0)
        assert coord._refill.in_progress is True

        for i in range(5):
            coord._refill.buffer.append(
                {
                    "timestamp": dt_util.now() + timedelta(minutes=i),
                    "volume": 698.0 + i * 0.2,
                }
            )

        coord._refill.start_time = dt_util.now() - timedelta(minutes=5)

        await coord._process_volume_reading(699.0)
        assert coord._refill.in_progress is False
        assert coord._last_refill_date is not None

    @pytest.mark.asyncio
    async def test_refill_records_volume_added(self, mock_hass):
        """After refill, the volume added should be recorded."""
        coord = make_coordinator(
            mock_hass,
            refill_threshold=50,
            refill_stabilization_minutes=0,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(400.0)

        await coord._process_volume_reading(700.0)
        coord._refill.start_time = dt_util.now() - timedelta(minutes=60)
        await coord._process_volume_reading(700.0)

        assert coord._last_refill_volume is not None
        assert coord._last_refill_volume > 0

    @pytest.mark.asyncio
    async def test_refill_does_not_clear_consumption(self, mock_hass):
        """Refill should NOT clear consumption history (BUG-3 fix verification)."""
        coord = make_coordinator(
            mock_hass,
            refill_threshold=50,
            noise_threshold=0.1,
            reading_debounce_seconds=0,
            reading_buffer_size=1,
        )
        await coord._process_volume_reading(500.0)
        await coord._process_volume_reading(490.0)

        daily_before = coord._consumption.get_daily_totals()
        assert len(daily_before) > 0

        await coord._record_refill(700.0, 210.0)

        daily_after = coord._consumption.get_daily_totals()
        assert len(daily_after) > 0
        assert daily_after == daily_before


# ---------------------------------------------------------------------------
# Manual refill handling
# ---------------------------------------------------------------------------

class TestManualRefill:
    """Tests for manual refill via async_record_refill."""

    @pytest.mark.asyncio
    async def test_manual_refill_with_volume(self, mock_hass):
        """Manual refill with specified volume should add to current volume."""
        coord = make_coordinator(
            mock_hass, reading_debounce_seconds=0, reading_buffer_size=1,
        )
        await coord._process_volume_reading(400.0)

        await coord.async_record_refill(300.0)

        assert coord._current_volume == 700.0
        assert coord._last_refill_volume == 300.0

    @pytest.mark.asyncio
    async def test_manual_refill_without_volume(self, mock_hass):
        """Manual refill without volume should mark refill with unknown amount."""
        coord = make_coordinator(
            mock_hass, reading_debounce_seconds=0, reading_buffer_size=1,
        )
        await coord._process_volume_reading(400.0)

        await coord.async_record_refill(None)

        assert coord._last_refill_date is not None
        assert coord._last_refill_volume is None


# ---------------------------------------------------------------------------
# History serialization (BUG-5 fix)
# ---------------------------------------------------------------------------

class TestHistorySerialization:
    """Tests for history serialization round-trip."""

    @pytest.mark.asyncio
    async def test_refill_timestamps_serialized_as_iso_strings(self, mock_hass):
        """Refill history timestamps should be ISO strings, not datetime objects."""
        coord = make_coordinator(
            mock_hass, reading_buffer_size=1, reading_debounce_seconds=0,
        )
        await coord._process_volume_reading(400.0)
        await coord._record_refill(600.0, 200.0)

        for entry in coord._refill_history:
            assert isinstance(entry["timestamp"], str)
            parsed = dt_util.parse_datetime(entry["timestamp"])
            assert parsed is not None

    def test_serialize_history_produces_json_safe_dict(self, mock_hass):
        """_serialize_history should return a dict with no datetime objects."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)

        coord._consumption.record(5.0, dt_util.now())
        coord._last_refill_date = dt_util.now()
        coord._last_refill_volume = 200.0
        coord._refill_history = [
            {
                "timestamp": dt_util.now().isoformat(),
                "volume_added": 200.0,
                "total_volume": 600.0,
            }
        ]

        history = coord._serialize_history()

        json_str = json.dumps(history)
        assert json_str is not None

        assert "version" in history
        assert "consumption_daily" in history
        assert "refill_history" in history
        assert "last_refill" in history
        assert isinstance(history["last_refill"]["timestamp"], str)

    @pytest.mark.asyncio
    async def test_load_history_round_trip(self, mock_hass):
        """Data serialized should be loadable back."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)

        coord._consumption.record(5.0, dt_util.now())
        coord._last_refill_date = dt_util.now()
        coord._last_refill_volume = 200.0
        coord._refill_history = [
            {
                "timestamp": dt_util.now().isoformat(),
                "volume_added": 200.0,
                "total_volume": 600.0,
            }
        ]

        serialized = coord._serialize_history()

        coord2 = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord2._store.async_load = AsyncMock(return_value=serialized)
        await coord2._async_load_history()

        assert coord2._history_loaded is True
        assert len(coord2._refill_history) == 1
        assert coord2._last_refill_volume == 200.0


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------

class TestDerivedValues:
    """Tests for derived value calculations."""

    def test_get_daily_consumption(self, mock_hass):
        """get_daily_consumption should delegate to tracker."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(10.0, dt_util.now() - timedelta(days=1))
        daily = coord.get_daily_consumption()
        assert daily > 0

    def test_get_daily_consumption_kwh(self, mock_hass):
        """Daily kWh should be daily liters * conversion factor."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(10.0, dt_util.now() - timedelta(days=1))
        kwh = coord.get_daily_consumption_kwh()
        daily = coord.get_daily_consumption()
        assert abs(kwh - daily * KEROSENE_KWH_PER_LITER) < 0.01

    def test_get_monthly_consumption(self, mock_hass):
        """Monthly consumption should return this month's total."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(5.0, dt_util.now())
        monthly = coord.get_monthly_consumption()
        assert monthly == 5.0

    def test_get_days_until_empty(self, mock_hass):
        """Days until empty should use current volume and consumption rate."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(10.0, dt_util.now() - timedelta(days=1))
        coord._consumption.record(10.0, dt_util.now() - timedelta(days=2))
        days = coord.get_days_until_empty()
        assert days is not None
        assert days > 0

    def test_get_normalized_volume_without_temp(self, mock_hass):
        """Normalized volume without temperature should equal raw volume."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        assert coord._current_temperature is None
        raw = coord._current_volume
        normalized = coord.get_normalized_volume()
        assert normalized == raw

    def test_get_normalized_volume_with_temp(self, mock_hass):
        """Normalized volume with temperature should differ from raw."""
        coord = make_coordinator(
            mock_hass, initial_air_gap=20.0, temperature_sensor="sensor.temp",
        )
        coord._current_temperature = 25.0
        raw = coord._current_volume
        normalized = coord.get_normalized_volume()
        assert normalized is not None
        assert normalized < raw


# ---------------------------------------------------------------------------
# Data publish
# ---------------------------------------------------------------------------

class TestPublish:
    """Tests for the _publish method."""

    def test_publish_creates_data_snapshot(self, mock_hass):
        """_publish should create a HeatingOilData snapshot."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._publish()
        data = coord.data
        assert isinstance(data, HeatingOilData)
        assert data.volume == coord._current_volume
        assert data.daily_consumption == 0.0
        assert data.monthly_consumption == 0.0

    def test_publish_includes_all_fields(self, mock_hass):
        """Published data should include all HeatingOilData fields."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(10.0, dt_util.now() - timedelta(days=1))
        coord._last_refill_date = dt_util.now()
        coord._last_refill_volume = 200.0
        coord._publish()

        data = coord.data
        assert data.volume is not None
        assert data.daily_consumption > 0
        assert data.last_refill_date is not None
        assert data.last_refill_volume == 200.0


# ---------------------------------------------------------------------------
# Restore methods
# ---------------------------------------------------------------------------

class TestRestore:
    """Tests for state restoration methods."""

    def test_restore_volume(self, mock_hass):
        """restore_volume should set current and previous volume."""
        coord = make_coordinator(mock_hass)
        coord.restore_volume(500.0)
        assert coord._current_volume == 500.0
        assert coord._previous_volume == 500.0

    def test_restore_last_refill(self, mock_hass):
        """restore_last_refill should set refill date and volume."""
        coord = make_coordinator(mock_hass)
        refill_date = dt_util.now()
        coord.restore_last_refill(refill_date, 200.0)
        assert coord._last_refill_date == refill_date
        assert coord._last_refill_volume == 200.0
