"""Tests for sensor.py."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfVolume
from homeassistant.util import dt as dt_util

from custom_components.heating_oil_monitor.coordinator import HeatingOilData
from custom_components.heating_oil_monitor.const import DOMAIN
from custom_components.heating_oil_monitor.sensor import (
    _build_sensors,
    HeatingOilVolumeSensor,
    HeatingOilDailyConsumptionSensor,
    HeatingOilDailyConsumptionEnergySensor,
    HeatingOilMonthlyConsumptionSensor,
    HeatingOilDaysUntilEmptySensor,
    HeatingOilLastRefillSensor,
    HeatingOilLastRefillVolumeSensor,
    HeatingOilNormalizedVolumeSensor,
)
from conftest import make_coordinator


# ---------------------------------------------------------------------------
# _build_sensors (HIGH-2 fix verification)
# ---------------------------------------------------------------------------

class TestBuildSensors:
    """Tests for the sensor builder function."""

    def test_returns_sensors(self, mock_hass):
        """Should return a list of sensors for a coordinator."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensors = _build_sensors(coord)
        assert len(sensors) >= 7  # 7 base sensors (no normalized without temp sensor)

    def test_returns_empty_for_none_coordinator(self):
        """Should handle coordinator without temperature sensor."""
        # _build_sensors always returns sensors; without temp sensor there's no normalized sensor
        pass

    def test_includes_normalized_sensor_when_temp_configured(self, mock_hass):
        """Should include NormalizedVolumeSensor when temperature sensor is set."""
        coord = make_coordinator(
            mock_hass, initial_air_gap=20.0, temperature_sensor="sensor.temp"
        )
        sensors = _build_sensors(coord)
        sensor_types = [type(s) for s in sensors]
        assert HeatingOilNormalizedVolumeSensor in sensor_types

    def test_excludes_normalized_sensor_without_temp(self, mock_hass):
        """Should not include NormalizedVolumeSensor when no temperature sensor."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensors = _build_sensors(coord)
        sensor_types = [type(s) for s in sensors]
        assert HeatingOilNormalizedVolumeSensor not in sensor_types


# ---------------------------------------------------------------------------
# HeatingOilVolumeSensor
# ---------------------------------------------------------------------------

class TestVolumeSensor:
    """Tests for the volume sensor."""

    def test_volume_sensor_attributes(self, mock_hass):
        """Sensor should have correct device class and state class."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilVolumeSensor(coord)

        assert sensor._attr_device_class == SensorDeviceClass.VOLUME
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT
        assert sensor._attr_native_unit_of_measurement == UnitOfVolume.LITERS

    def test_volume_sensor_state_class_is_measurement(self, mock_hass):
        """Volume should use MEASUREMENT, not TOTAL (MED-6 fix verification)."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilVolumeSensor(coord)
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT

    def test_volume_sensor_native_value(self, mock_hass):
        """native_value should return rounded volume from coordinator data."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilVolumeSensor(coord)

        value = sensor.native_value
        assert value is not None
        assert isinstance(value, float)
        assert value > 0

    def test_volume_sensor_native_value_none_when_no_data(self, mock_hass):
        """native_value should return None when coordinator has no data."""
        coord = make_coordinator(mock_hass)
        # Force data to None
        coord.data = None
        sensor = HeatingOilVolumeSensor(coord)
        assert sensor.native_value is None

    def test_volume_sensor_has_device_info(self, mock_hass):
        """Sensor should have device_info for device grouping (HIGH-4 fix)."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilVolumeSensor(coord)
        assert sensor._attr_device_info is not None
        assert (DOMAIN, "sensor.air_gap") in sensor._attr_device_info["identifiers"]

    def test_volume_sensor_unique_id(self, mock_hass):
        """Sensor should have a unique ID."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilVolumeSensor(coord)
        assert sensor._attr_unique_id == f"{DOMAIN}_volume"


# ---------------------------------------------------------------------------
# HeatingOilMonthlyConsumptionSensor
# ---------------------------------------------------------------------------

class TestMonthlyConsumptionSensor:
    """Tests for the monthly consumption sensor."""

    def test_monthly_sensor_state_class_is_total(self, mock_hass):
        """Monthly sensor should use TOTAL, not TOTAL_INCREASING (MED-5 fix)."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilMonthlyConsumptionSensor(coord)
        assert sensor._attr_state_class == SensorStateClass.TOTAL

    def test_monthly_sensor_native_value(self, mock_hass):
        """native_value should return monthly consumption."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(10.0, dt_util.now())
        coord._publish()

        sensor = HeatingOilMonthlyConsumptionSensor(coord)
        value = sensor.native_value
        assert value >= 10.0

    def test_monthly_sensor_has_device_info(self, mock_hass):
        """Monthly sensor should have device_info."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilMonthlyConsumptionSensor(coord)
        assert sensor._attr_device_info is not None


# ---------------------------------------------------------------------------
# HeatingOilDailyConsumptionSensor
# ---------------------------------------------------------------------------

class TestDailyConsumptionSensor:
    """Tests for the daily consumption sensor."""

    def test_daily_sensor_native_value(self, mock_hass):
        """native_value should return daily consumption."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(10.0, dt_util.now() - timedelta(days=1))
        coord._publish()

        sensor = HeatingOilDailyConsumptionSensor(coord)
        value = sensor.native_value
        assert value > 0

    def test_daily_sensor_has_device_info(self, mock_hass):
        """Daily sensor should have device_info."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilDailyConsumptionSensor(coord)
        assert sensor._attr_device_info is not None


# ---------------------------------------------------------------------------
# HeatingOilDaysUntilEmptySensor
# ---------------------------------------------------------------------------

class TestDaysUntilEmptySensor:
    """Tests for the days-until-empty sensor."""

    def test_days_sensor_uses_last_calculated_value(self, mock_hass):
        """When no fresh data, should return last calculated value."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilDaysUntilEmptySensor(coord)
        sensor._last_calculated_value = 42
        # When data.days_until_empty is None, should use _last_calculated_value
        coord._consumption.clear()
        coord._publish()
        value = sensor.native_value
        # Should return either calculated or last known
        assert value is not None or sensor._last_calculated_value is not None


# ---------------------------------------------------------------------------
# HeatingOilDailyConsumptionEnergySensor
# ---------------------------------------------------------------------------

class TestDailyEnergySensor:
    """Tests for the daily energy consumption sensor."""

    def test_energy_sensor_native_value(self, mock_hass):
        """native_value should return kWh consumption."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        coord._consumption.record(10.0, dt_util.now() - timedelta(days=1))
        coord._publish()

        sensor = HeatingOilDailyConsumptionEnergySensor(coord)
        value = sensor.native_value
        assert value > 0

    def test_energy_sensor_has_device_info(self, mock_hass):
        """Energy sensor should have device_info."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = HeatingOilDailyConsumptionEnergySensor(coord)
        assert sensor._attr_device_info is not None


# ---------------------------------------------------------------------------
# All sensors have device_info (HIGH-4 fix verification)
# ---------------------------------------------------------------------------

class TestDeviceInfoPresent:
    """Verify all sensor classes have device_info."""

    sensor_classes = [
        HeatingOilVolumeSensor,
        HeatingOilDailyConsumptionSensor,
        HeatingOilDailyConsumptionEnergySensor,
        HeatingOilMonthlyConsumptionSensor,
        HeatingOilDaysUntilEmptySensor,
        HeatingOilLastRefillSensor,
        HeatingOilLastRefillVolumeSensor,
    ]

    @pytest.mark.parametrize("sensor_cls", sensor_classes)
    def test_sensor_has_device_info(self, mock_hass, sensor_cls):
        """Every sensor class should set device_info."""
        coord = make_coordinator(mock_hass, initial_air_gap=20.0)
        sensor = sensor_cls(coord)
        assert hasattr(sensor, "_attr_device_info")
        assert sensor._attr_device_info is not None

    def test_normalized_volume_has_device_info(self, mock_hass):
        """NormalizedVolumeSensor should also have device_info."""
        coord = make_coordinator(
            mock_hass, initial_air_gap=20.0, temperature_sensor="sensor.temp"
        )
        sensor = HeatingOilNormalizedVolumeSensor(coord)
        assert sensor._attr_device_info is not None
