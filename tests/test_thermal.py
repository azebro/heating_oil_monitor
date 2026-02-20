"""Tests for thermal normalization."""

from __future__ import annotations

from custom_components.heating_oil_monitor.thermal import normalize_volume
from custom_components.heating_oil_monitor.const import THERMAL_EXPANSION_COEFFICIENT


# ---------------------------------------------------------------------------
# Basic normalization
# ---------------------------------------------------------------------------

class TestNormalization:
    """Tests for temperature normalization."""

    def test_no_temperature_returns_measured(self):
        """When temperature is None, measured volume should be returned unchanged."""
        assert normalize_volume(100.0, None, 15.0) == 100.0

    def test_at_reference_temperature_returns_measured(self):
        """At reference temperature, normalized == measured."""
        normalized = normalize_volume(100.0, 15.0, 15.0)
        assert normalized == 100.0

    def test_above_reference_reduces_volume(self):
        """Temperature above reference should reduce normalized volume."""
        normalized = normalize_volume(100.0, 25.0, 15.0)
        assert normalized < 100.0

    def test_below_reference_increases_volume(self):
        """Temperature below reference should increase normalized volume."""
        normalized = normalize_volume(100.0, 5.0, 15.0)
        assert normalized > 100.0

    def test_large_temperature_difference(self):
        """Large temperature differences should produce larger corrections."""
        small_diff = abs(normalize_volume(100.0, 16.0, 15.0) - 100.0)
        large_diff = abs(normalize_volume(100.0, 25.0, 15.0) - 100.0)
        assert large_diff > small_diff

    def test_correction_is_proportional_to_volume(self):
        """Correction amount should scale with volume."""
        correction_small = abs(normalize_volume(100.0, 25.0, 15.0) - 100.0)
        correction_large = abs(normalize_volume(1000.0, 25.0, 15.0) - 1000.0)
        # Should be roughly 10x
        assert abs(correction_large / correction_small - 10.0) < 0.1

    def test_zero_volume(self):
        """Zero volume should remain zero regardless of temperature."""
        assert normalize_volume(0.0, 25.0, 15.0) == 0.0

    def test_uses_expansion_coefficient(self):
        """Normalization should use the defined thermal expansion coefficient."""
        measured = 1000.0
        current_temp = 25.0
        ref_temp = 15.0
        temp_diff = current_temp - ref_temp
        expected_factor = 1 + (THERMAL_EXPANSION_COEFFICIENT * temp_diff)
        expected = measured / expected_factor
        actual = normalize_volume(measured, current_temp, ref_temp)
        assert abs(actual - expected) < 0.001
