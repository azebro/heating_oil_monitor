"""Tests for RefillStabilizer."""

from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.heating_oil_monitor.refill import RefillStabilizer


# ---------------------------------------------------------------------------
# Start and reset
# ---------------------------------------------------------------------------

class TestStartAndReset:
    """Tests for starting and resetting stabilization."""

    def test_start_sets_state(self):
        """Starting should set in_progress, start_time, pre_refill_volume."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        assert stab.in_progress is True
        assert stab.start_time == now
        assert stab.pre_refill_volume == 400.0
        assert len(stab.buffer) == 1
        assert stab.buffer[0]["volume"] == 500.0

    def test_reset_clears_state(self):
        """Reset should clear all state."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)
        stab.reset()

        assert stab.in_progress is False
        assert stab.start_time is None
        assert stab.buffer == []
        assert stab.pre_refill_volume is None

    def test_start_with_none_pre_refill(self):
        """Starting with None pre-refill volume should work."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, None)

        assert stab.in_progress is True
        assert stab.pre_refill_volume is None


# ---------------------------------------------------------------------------
# Adding readings
# ---------------------------------------------------------------------------

class TestAddReading:
    """Tests for adding readings during stabilization."""

    def test_add_reading_appends_to_buffer(self):
        """Each reading should be appended to the buffer."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        stab.add_reading(501.0, now + timedelta(minutes=1))
        stab.add_reading(499.5, now + timedelta(minutes=2))

        assert len(stab.buffer) == 3  # 1 from start + 2 added

    def test_buffer_preserves_all_readings(self):
        """All readings should be preserved in order."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        for i in range(10):
            stab.add_reading(500.0 + i, now + timedelta(minutes=i + 1))

        assert len(stab.buffer) == 11


# ---------------------------------------------------------------------------
# Time tracking
# ---------------------------------------------------------------------------

class TestTimeTracking:
    """Tests for elapsed time tracking."""

    def test_minutes_elapsed(self):
        """Should correctly calculate minutes elapsed."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        later = now + timedelta(minutes=15)
        assert stab.minutes_elapsed(later) == 15.0

    def test_minutes_elapsed_no_start_time(self):
        """Should return 0 if no start time."""
        stab = RefillStabilizer(20.0, 30, 1.0)
        assert stab.minutes_elapsed(datetime(2025, 1, 1)) == 0.0


# ---------------------------------------------------------------------------
# Stability check
# ---------------------------------------------------------------------------

class TestStability:
    """Tests for stability checking."""

    def test_stable_with_consistent_readings(self):
        """Stable readings (low variance) should return True."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        for i in range(4):
            stab.add_reading(500.0 + (i * 0.1), now + timedelta(minutes=i + 1))

        assert stab.is_stable() is True

    def test_unstable_with_varied_readings(self):
        """Varied readings should return False."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        # Large swings
        for i, vol in enumerate([510.0, 490.0, 520.0, 480.0]):
            stab.add_reading(vol, now + timedelta(minutes=i + 1))

        assert stab.is_stable() is False

    def test_not_stable_with_few_readings(self):
        """Fewer than 5 readings should never be stable."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)
        stab.add_reading(500.0, now + timedelta(minutes=1))

        assert stab.is_stable() is False

    def test_stability_uses_last_five_readings(self):
        """Stability should only consider the last 5 readings."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(200.0, now, 100.0)  # Wild first reading

        # Add noisy readings
        stab.add_reading(300.0, now + timedelta(minutes=1))
        stab.add_reading(250.0, now + timedelta(minutes=2))

        # Then 4 stable readings (total 5 in last window incl above)
        # Actually we need the last 5 to be stable
        for i in range(5):
            stab.add_reading(500.0 + i * 0.05, now + timedelta(minutes=10 + i))

        assert stab.is_stable() is True


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------

class TestFinalization:
    """Tests for should_finalize and stable_volume."""

    def test_should_finalize_by_time(self):
        """Should finalize when stabilization minutes have passed."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        future = now + timedelta(minutes=31)
        assert stab.should_finalize(future) is True

    def test_should_finalize_by_stability(self):
        """Should finalize when readings are stable (even before timeout)."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 60, 1.0)
        stab.start(500.0, now, 400.0)

        for i in range(4):
            stab.add_reading(500.0 + i * 0.1, now + timedelta(minutes=i + 1))

        still_early = now + timedelta(minutes=5)
        assert stab.should_finalize(still_early) is True

    def test_should_not_finalize_early_unstable(self):
        """Should NOT finalize if time hasn't passed and readings aren't stable."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 60, 1.0)
        stab.start(500.0, now, 400.0)

        # Only 2 readings, unstable
        stab.add_reading(520.0, now + timedelta(minutes=1))
        still_early = now + timedelta(minutes=2)
        assert stab.should_finalize(still_early) is False

    def test_stable_volume_returns_median(self):
        """stable_volume should return median of recent readings."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        stab = RefillStabilizer(20.0, 30, 1.0)
        stab.start(500.0, now, 400.0)

        for i in range(4):
            stab.add_reading(500.0 + (i * 0.1), now + timedelta(minutes=i + 1))

        stable = stab.stable_volume(0.0)
        assert stable > 0.0
        # Buffer: [500.0, 500.0, 500.1, 500.2, 500.3], sorted median = 500.1
        assert abs(stable - 500.1) < 0.01

    def test_stable_volume_empty_buffer_uses_fallback(self):
        """Empty buffer should return the fallback volume."""
        stab = RefillStabilizer(20.0, 30, 1.0)
        assert stab.stable_volume(999.0) == 999.0

    def test_stable_volume_none_fallback(self):
        """None fallback with empty buffer should return 0."""
        stab = RefillStabilizer(20.0, 30, 1.0)
        assert stab.stable_volume(None) == 0.0
