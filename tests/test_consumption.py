"""Tests for ConsumptionTracker."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

pytest.importorskip("homeassistant")

from homeassistant.util import dt as dt_util

from custom_components.heating_oil_monitor.consumption import ConsumptionTracker


# ---------------------------------------------------------------------------
# Basic recording and retrieval
# ---------------------------------------------------------------------------

class TestBasicRecording:
    """Tests for basic consumption recording."""

    def test_record_single_consumption(self):
        """A single consumption entry should be stored."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        now = dt_util.now()
        tracker.record(10.0, now)
        totals = tracker.get_daily_totals()
        assert len(totals) == 1
        assert sum(totals.values()) == 10.0

    def test_record_multiple_same_day(self):
        """Multiple entries on the same day should sum."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        now = dt_util.now()
        tracker.record(5.0, now)
        tracker.record(3.0, now)
        totals = tracker.get_daily_totals()
        assert len(totals) == 1
        day_key = list(totals.keys())[0]
        assert totals[day_key] == 8.0

    def test_record_multiple_days(self):
        """Entries on different days should be stored separately."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        now = dt_util.now()
        tracker.record(5.0, now - timedelta(days=1))
        tracker.record(3.0, now)
        totals = tracker.get_daily_totals()
        assert len(totals) == 2

    def test_clear_empties_history(self):
        """clear() should remove all history."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        tracker.record(10.0, dt_util.now())
        tracker.clear()
        assert tracker.get_daily_totals() == {}


# ---------------------------------------------------------------------------
# Daily consumption calculation
# ---------------------------------------------------------------------------

class TestDailyConsumption:
    """Tests for daily consumption averaging."""

    def test_consumption_daily_average(self):
        """Average should be computed over the configured period."""
        now = dt_util.now()
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        tracker.record(10.0, now - timedelta(days=1))
        tracker.record(10.0, now - timedelta(days=2))

        daily = tracker.get_daily_consumption(now)
        assert daily > 0.0

    def test_no_data_returns_zero(self):
        """No data should return 0."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        assert tracker.get_daily_consumption(dt_util.now()) == 0.0

    def test_only_old_data_returns_zero(self):
        """Data outside the consumption window should return 0."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        old = dt_util.now() - timedelta(days=30)
        tracker.record(10.0, old)
        daily = tracker.get_daily_consumption(dt_util.now())
        assert daily == 0.0

    def test_consumption_period_accuracy(self):
        """Daily average with known values should be calculable."""
        now = dt_util.now()
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        # Record 10L each day for 5 days
        for i in range(1, 6):
            tracker.record(10.0, now - timedelta(days=i))

        daily = tracker.get_daily_consumption(now)
        # Total is 50L over ~5 days, expect ~10 L/day
        assert 8.0 < daily < 12.0


# ---------------------------------------------------------------------------
# Monthly consumption
# ---------------------------------------------------------------------------

class TestMonthlyConsumption:
    """Tests for monthly aggregation."""

    def test_monthly_consumption_this_month(self):
        """Should sum only entries from the current month."""
        now = dt_util.now()
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        tracker.record(10.0, now)
        tracker.record(5.0, now - timedelta(days=1))
        monthly = tracker.get_monthly_consumption(now)
        assert monthly >= 10.0

    def test_monthly_consumption_excludes_last_month(self):
        """Entries from last month should NOT be included."""
        now = dt_util.now()
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        # Record in previous month
        last_month = now.replace(day=1) - timedelta(days=1)
        tracker.record(99.0, last_month)
        # Record today
        tracker.record(5.0, now)
        monthly = tracker.get_monthly_consumption(now)
        assert monthly == 5.0

    def test_monthly_consumption_empty(self):
        """No data should return 0."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        assert tracker.get_monthly_consumption(dt_util.now()) == 0.0


# ---------------------------------------------------------------------------
# Days until empty
# ---------------------------------------------------------------------------

class TestDaysUntilEmpty:
    """Tests for days-until-empty estimation."""

    def test_days_until_empty_with_data(self):
        """Should estimate days based on consumption rate and volume."""
        now = dt_util.now()
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        tracker.record(10.0, now - timedelta(days=1))
        tracker.record(10.0, now - timedelta(days=2))

        days = tracker.get_days_until_empty(now, current_volume=100.0)
        assert days is not None
        assert days > 0

    def test_days_until_empty_zero_volume(self):
        """Zero volume should return 0."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        tracker.record(10.0, dt_util.now() - timedelta(days=1))
        assert tracker.get_days_until_empty(dt_util.now(), current_volume=0.0) == 0

    def test_days_until_empty_negative_volume(self):
        """Negative volume should return 0."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        tracker.record(10.0, dt_util.now() - timedelta(days=1))
        assert tracker.get_days_until_empty(dt_util.now(), current_volume=-5.0) == 0

    def test_days_until_empty_none_volume(self):
        """None volume should return 0."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        assert tracker.get_days_until_empty(dt_util.now(), current_volume=None) == 0

    def test_days_until_empty_no_consumption(self):
        """No consumption history should return None."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        assert tracker.get_days_until_empty(dt_util.now(), current_volume=100.0) is None


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

class TestPruning:
    """Tests for history pruning."""

    def test_prune_removes_old_entries(self):
        """Entries older than max_history_days should be removed."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=30)
        now = dt_util.now()

        # Add old entry
        tracker.record(10.0, now - timedelta(days=40))
        # Add recent entry
        tracker.record(5.0, now)

        # Only the recent entry should remain
        totals = tracker.get_daily_totals()
        assert len(totals) == 1
        assert sum(totals.values()) == 5.0

    def test_prune_preserves_recent_entries(self):
        """Entries within max_history_days should be kept."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        now = dt_util.now()

        for i in range(10):
            tracker.record(1.0, now - timedelta(days=i))

        totals = tracker.get_daily_totals()
        assert len(totals) == 10

    def test_docstring_matches_behavior(self):
        """Verify the _prune docstring says max_history_days (BUG-4 fix)."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        assert "max_history_days" in tracker._prune.__doc__


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

class TestSerialization:
    """Tests for get/set daily_totals round-trip."""

    def test_get_set_daily_totals_round_trip(self):
        """set_daily_totals should restore data from get_daily_totals."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        now = dt_util.now()
        tracker.record(10.0, now - timedelta(days=1))
        tracker.record(5.0, now)

        saved = tracker.get_daily_totals()

        tracker2 = ConsumptionTracker(consumption_days=7, max_history_days=365)
        tracker2.set_daily_totals(saved)

        assert tracker2.get_daily_totals() == saved

    def test_get_history_entries_sorted(self):
        """get_history_entries should return sorted by timestamp."""
        tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)
        now = dt_util.now()
        tracker.record(5.0, now)
        tracker.record(3.0, now - timedelta(days=2))
        tracker.record(7.0, now - timedelta(days=1))

        entries = tracker.get_history_entries()
        timestamps = [e["timestamp"] for e in entries]
        assert timestamps == sorted(timestamps)
