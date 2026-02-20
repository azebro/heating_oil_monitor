"""Tests for geometry module - horizontal cylinder tank volume calculation."""

from __future__ import annotations

import math

from custom_components.heating_oil_monitor.geometry import calculate_volume


# ---------------------------------------------------------------------------
# Basic calculations
# ---------------------------------------------------------------------------

class TestBasicCalculation:
    """Tests for standard volume calculations."""

    def test_empty_tank(self):
        """Air gap equal to diameter should return 0 (empty)."""
        assert calculate_volume(air_gap_cm=100, diameter_cm=100, length_cm=100) == 0.0

    def test_full_tank(self):
        """Air gap of 0 should return full cylinder volume."""
        volume = calculate_volume(air_gap_cm=0, diameter_cm=100, length_cm=100)
        expected = math.pi * (50**2) * 100 / 1000.0
        assert volume == expected

    def test_half_full(self):
        """Air gap at half diameter should return half the full volume."""
        volume = calculate_volume(air_gap_cm=50, diameter_cm=100, length_cm=100)
        full = math.pi * (50**2) * 100 / 1000.0
        # Half-full cylinder is exactly half the full volume
        assert abs(volume - full / 2) < 0.01

    def test_quarter_fill(self):
        """Small fill level should be positive and less than half."""
        volume = calculate_volume(air_gap_cm=75, diameter_cm=100, length_cm=100)
        half_vol = calculate_volume(air_gap_cm=50, diameter_cm=100, length_cm=100)
        assert volume > 0
        assert volume < half_vol

    def test_three_quarter_fill(self):
        """Large fill should be more than half but less than full."""
        volume = calculate_volume(air_gap_cm=25, diameter_cm=100, length_cm=100)
        half_vol = calculate_volume(air_gap_cm=50, diameter_cm=100, length_cm=100)
        full_vol = calculate_volume(air_gap_cm=0, diameter_cm=100, length_cm=100)
        assert volume > half_vol
        assert volume < full_vol

    def test_volume_increases_with_less_air_gap(self):
        """Volume should monotonically increase as air gap decreases."""
        prev = 0.0
        for gap in [90, 70, 50, 30, 10, 0]:
            vol = calculate_volume(air_gap_cm=gap, diameter_cm=100, length_cm=100)
            assert vol >= prev
            prev = vol

    def test_realistic_tank_dimensions(self):
        """Test with realistic heating oil tank dimensions."""
        # 124cm diameter, 180cm length, 20cm air gap
        volume = calculate_volume(air_gap_cm=20, diameter_cm=124, length_cm=180)
        assert volume > 0
        full_volume = calculate_volume(air_gap_cm=0, diameter_cm=124, length_cm=180)
        assert volume < full_volume


# ---------------------------------------------------------------------------
# Input guards (LOW-6 fix)
# ---------------------------------------------------------------------------

class TestInputGuards:
    """Tests for input validation / boundary conditions."""

    def test_negative_air_gap_clamped_to_zero(self):
        """Negative air gap should be treated as 0 (full tank)."""
        negative = calculate_volume(air_gap_cm=-5, diameter_cm=100, length_cm=100)
        full = calculate_volume(air_gap_cm=0, diameter_cm=100, length_cm=100)
        assert negative == full

    def test_zero_diameter_returns_zero(self):
        """Zero diameter should return 0."""
        assert calculate_volume(air_gap_cm=0, diameter_cm=0, length_cm=100) == 0.0

    def test_negative_diameter_returns_zero(self):
        """Negative diameter should return 0."""
        assert calculate_volume(air_gap_cm=0, diameter_cm=-50, length_cm=100) == 0.0

    def test_zero_length_returns_zero(self):
        """Zero length should return 0."""
        assert calculate_volume(air_gap_cm=0, diameter_cm=100, length_cm=0) == 0.0

    def test_negative_length_returns_zero(self):
        """Negative length should return 0."""
        assert calculate_volume(air_gap_cm=0, diameter_cm=100, length_cm=-50) == 0.0

    def test_air_gap_exceeds_diameter(self):
        """Air gap larger than diameter should return 0."""
        assert calculate_volume(air_gap_cm=150, diameter_cm=100, length_cm=100) == 0.0
