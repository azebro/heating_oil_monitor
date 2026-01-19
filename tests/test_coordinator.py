from __future__ import annotations

import pytest

homeassistant = pytest.importorskip("homeassistant")

from custom_components.heating_oil_monitor.coordinator import HeatingOilCoordinator


def test_coordinator_importable() -> None:
    assert HeatingOilCoordinator is not None
