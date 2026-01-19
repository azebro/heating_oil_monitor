from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.heating_oil_monitor.refill import RefillStabilizer


def test_refill_stabilizer_start_and_reset() -> None:
    now = datetime(2025, 1, 1, 12, 0, 0)
    stabilizer = RefillStabilizer(20.0, 30, 1.0)
    stabilizer.start(500.0, now, 400.0)

    assert stabilizer.in_progress is True
    assert stabilizer.start_time == now
    assert stabilizer.pre_refill_volume == 400.0
    assert len(stabilizer.buffer) == 1

    stabilizer.reset()
    assert stabilizer.in_progress is False
    assert stabilizer.start_time is None
    assert stabilizer.buffer == []


def test_refill_stabilizer_stable_volume() -> None:
    now = datetime(2025, 1, 1, 12, 0, 0)
    stabilizer = RefillStabilizer(20.0, 30, 1.0)
    stabilizer.start(500.0, now, 400.0)

    for i in range(4):
        stabilizer.add_reading(500.0 + (i * 0.1), now + timedelta(minutes=i + 1))

    assert stabilizer.is_stable() is True
    stable = stabilizer.stable_volume(0.0)
    assert stable > 0.0
