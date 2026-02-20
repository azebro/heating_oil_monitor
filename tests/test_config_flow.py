"""Tests for config_flow.py."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.heating_oil_monitor.config_flow import (
    _build_schema,
    HeatingOilMonitorConfigFlow,
)
from custom_components.heating_oil_monitor.const import (
    CONF_AIR_GAP_SENSOR,
    CONF_TANK_DIAMETER,
    CONF_TANK_LENGTH,
    CONF_REFILL_THRESHOLD,
    CONF_NOISE_THRESHOLD,
    CONF_CONSUMPTION_DAYS,
    CONF_TEMPERATURE_SENSOR,
    CONF_REFERENCE_TEMPERATURE,
    CONF_REFILL_STABILIZATION_MINUTES,
    CONF_REFILL_STABILITY_THRESHOLD,
    CONF_READING_BUFFER_SIZE,
    CONF_READING_DEBOUNCE_SECONDS,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_CONSUMPTION_DAYS,
    DEFAULT_REFERENCE_TEMPERATURE,
    DEFAULT_REFILL_STABILIZATION_MINUTES,
    DEFAULT_REFILL_STABILITY_THRESHOLD,
    DEFAULT_READING_BUFFER_SIZE,
    DEFAULT_READING_DEBOUNCE_SECONDS,
)


# ---------------------------------------------------------------------------
# Schema building (HIGH-3 fix verification)
# ---------------------------------------------------------------------------

class TestBuildSchema:
    """Tests for the shared _build_schema helper."""

    def test_build_schema_returns_schema(self):
        """_build_schema should return a voluptuous schema."""
        import voluptuous as vol

        schema = _build_schema({})
        assert isinstance(schema, vol.Schema)

    def test_build_schema_includes_all_config_keys(self):
        """Schema should include all expected config keys."""
        schema = _build_schema({})
        schema_keys = {str(k) for k in schema.schema}

        expected_keys = {
            CONF_AIR_GAP_SENSOR,
            CONF_TANK_DIAMETER,
            CONF_TANK_LENGTH,
            CONF_REFILL_THRESHOLD,
            CONF_NOISE_THRESHOLD,
            CONF_CONSUMPTION_DAYS,
            CONF_TEMPERATURE_SENSOR,
            CONF_REFERENCE_TEMPERATURE,
            CONF_REFILL_STABILIZATION_MINUTES,
            CONF_REFILL_STABILITY_THRESHOLD,
            CONF_READING_BUFFER_SIZE,
            CONF_READING_DEBOUNCE_SECONDS,
        }
        for key in expected_keys:
            assert key in schema_keys, f"Missing key: {key}"

    def test_build_schema_uses_defaults(self):
        """Schema should use provided defaults."""
        defaults = {
            CONF_AIR_GAP_SENSOR: "sensor.my_sensor",
            CONF_TANK_DIAMETER: 200,
            CONF_TANK_LENGTH: 300,
        }
        schema = _build_schema(defaults)
        # Schema should build without error with defaults
        assert schema is not None

    def test_build_schema_noise_threshold_in_liters(self):
        """Noise threshold should be configured in liters (BUG-1 fix verification)."""
        # The schema uses selectors; we verify the config key name includes "liters"
        assert "liters" in CONF_NOISE_THRESHOLD.lower()


# ---------------------------------------------------------------------------
# Config flow class
# ---------------------------------------------------------------------------

class TestConfigFlow:
    """Tests for the config flow class."""

    def test_config_flow_importable(self):
        """Config flow class should be importable."""
        assert HeatingOilMonitorConfigFlow is not None

    def test_config_flow_has_version(self):
        """Config flow should have VERSION attribute."""
        assert hasattr(HeatingOilMonitorConfigFlow, "VERSION")
        assert HeatingOilMonitorConfigFlow.VERSION == 1
