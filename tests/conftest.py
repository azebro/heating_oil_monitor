"""Shared fixtures for heating oil monitor tests."""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Ensure custom_components is importable
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

pytest.importorskip("homeassistant")

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.heating_oil_monitor.const import (
    DOMAIN,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_CONSUMPTION_DAYS,
    DEFAULT_REFERENCE_TEMPERATURE,
    DEFAULT_REFILL_STABILIZATION_MINUTES,
    DEFAULT_REFILL_STABILITY_THRESHOLD,
    DEFAULT_READING_BUFFER_SIZE,
    DEFAULT_READING_DEBOUNCE_SECONDS,
)
from custom_components.heating_oil_monitor.consumption import ConsumptionTracker


@pytest.fixture
def mock_hass():
    """Create a mocked HomeAssistant instance."""
    hass = MagicMock()
    hass.states.get.return_value = None
    hass.async_create_task.return_value = None
    hass.bus.async_listen.return_value = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def consumption_tracker():
    """Create a ConsumptionTracker with default settings."""
    return ConsumptionTracker(
        consumption_days=DEFAULT_CONSUMPTION_DAYS,
        max_history_days=365,
    )


def make_coordinator(
    mock_hass,
    air_gap_sensor="sensor.air_gap",
    tank_diameter=124.0,
    tank_length=180.0,
    entry_id="test_entry_id",
    initial_air_gap=None,
    **kwargs,
):
    """Create a HeatingOilCoordinator with mocked HA dependencies.

    This patches Store and async_track_state_change_event to avoid
    real HA interactions.
    """
    from custom_components.heating_oil_monitor.coordinator import HeatingOilCoordinator

    # Set up initial sensor state if requested
    if initial_air_gap is not None:
        mock_state = MagicMock()
        mock_state.state = str(initial_air_gap)
        mock_hass.states.get.return_value = mock_state
    else:
        mock_hass.states.get.return_value = None

    with (
        patch(
            "custom_components.heating_oil_monitor.coordinator.async_track_state_change_event"
        ),
        patch(
            "custom_components.heating_oil_monitor.coordinator.Store"
        ) as mock_store_cls,
        patch(
            "homeassistant.helpers.frame.report_usage"
        ),
    ):
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        mock_store.async_delay_save = MagicMock()
        mock_store_cls.return_value = mock_store

        coordinator = HeatingOilCoordinator(
            mock_hass,
            air_gap_sensor=air_gap_sensor,
            tank_diameter=tank_diameter,
            tank_length=tank_length,
            refill_threshold=kwargs.get("refill_threshold", DEFAULT_REFILL_THRESHOLD),
            noise_threshold=kwargs.get("noise_threshold", DEFAULT_NOISE_THRESHOLD),
            consumption_days=kwargs.get("consumption_days", DEFAULT_CONSUMPTION_DAYS),
            temperature_sensor=kwargs.get("temperature_sensor"),
            reference_temperature=kwargs.get(
                "reference_temperature", DEFAULT_REFERENCE_TEMPERATURE
            ),
            refill_stabilization_minutes=kwargs.get(
                "refill_stabilization_minutes", DEFAULT_REFILL_STABILIZATION_MINUTES
            ),
            refill_stability_threshold=kwargs.get(
                "refill_stability_threshold", DEFAULT_REFILL_STABILITY_THRESHOLD
            ),
            reading_buffer_size=kwargs.get(
                "reading_buffer_size", DEFAULT_READING_BUFFER_SIZE
            ),
            reading_debounce_seconds=kwargs.get(
                "reading_debounce_seconds", DEFAULT_READING_DEBOUNCE_SECONDS
            ),
            entry_id=entry_id,
        )

        # Store the mock store for assertions
        coordinator._store = mock_store

    return coordinator
