from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytest.importorskip("homeassistant")

from custom_components.heating_oil_monitor.consumption import ConsumptionTracker


def test_consumption_daily_average() -> None:
    now = datetime(2025, 1, 1, 12, 0, 0)
    tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)

    tracker.record(10.0, now - timedelta(days=1))
    tracker.record(10.0, now - timedelta(days=2))

    daily = tracker.get_daily_consumption(now)
    assert daily > 0.0


def test_days_until_empty() -> None:
    now = datetime(2025, 1, 1, 12, 0, 0)
    tracker = ConsumptionTracker(consumption_days=7, max_history_days=365)

    tracker.record(10.0, now - timedelta(days=1))
    tracker.record(10.0, now - timedelta(days=2))

    days = tracker.get_days_until_empty(now, current_volume=100.0)
    assert days is not None
    assert days > 0
