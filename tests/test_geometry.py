from __future__ import annotations

import math

from custom_components.heating_oil_monitor.geometry import calculate_volume


def test_calculate_volume_empty() -> None:
    assert calculate_volume(air_gap_cm=100, diameter_cm=100, length_cm=100) == 0.0


def test_calculate_volume_full() -> None:
    volume = calculate_volume(air_gap_cm=0, diameter_cm=100, length_cm=100)
    expected = math.pi * (50**2) * 100 / 1000.0
    assert volume == expected


def test_calculate_volume_half_full() -> None:
    volume = calculate_volume(air_gap_cm=50, diameter_cm=100, length_cm=100)
    assert volume > 0.0
    assert volume < math.pi * (50**2) * 100 / 1000.0
