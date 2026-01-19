from __future__ import annotations

from custom_components.heating_oil_monitor.thermal import normalize_volume


def test_normalize_volume_no_temperature() -> None:
    assert normalize_volume(100.0, None, 15.0) == 100.0


def test_normalize_volume_with_temperature() -> None:
    normalized = normalize_volume(100.0, 25.0, 15.0)
    assert normalized < 100.0
