"""Sensor platform for Heating Oil Monitor."""

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import HeatingOilCoordinator
from .const import (
    DOMAIN,
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
    KEROSENE_KWH_PER_LITER,
    THERMAL_EXPANSION_COEFFICIENT,
)

_LOGGER = logging.getLogger(__name__)


def _create_coordinator_and_sensors(
    hass: HomeAssistant,
    config: dict,
    entry_id: str | None = None,
) -> tuple[HeatingOilCoordinator | None, list[SensorEntity]]:
    """Create coordinator and sensor entities from config."""
    air_gap_sensor = config.get(CONF_AIR_GAP_SENSOR)
    tank_diameter = config.get(CONF_TANK_DIAMETER)
    tank_length = config.get(CONF_TANK_LENGTH)
    refill_threshold = config.get(CONF_REFILL_THRESHOLD, DEFAULT_REFILL_THRESHOLD)
    noise_threshold = config.get(CONF_NOISE_THRESHOLD, DEFAULT_NOISE_THRESHOLD)
    consumption_days = config.get(CONF_CONSUMPTION_DAYS, DEFAULT_CONSUMPTION_DAYS)
    temperature_sensor = config.get(CONF_TEMPERATURE_SENSOR)
    reference_temperature = config.get(
        CONF_REFERENCE_TEMPERATURE, DEFAULT_REFERENCE_TEMPERATURE
    )
    refill_stabilization_minutes = config.get(
        CONF_REFILL_STABILIZATION_MINUTES, DEFAULT_REFILL_STABILIZATION_MINUTES
    )
    refill_stability_threshold = config.get(
        CONF_REFILL_STABILITY_THRESHOLD, DEFAULT_REFILL_STABILITY_THRESHOLD
    )
    reading_buffer_size = config.get(
        CONF_READING_BUFFER_SIZE, DEFAULT_READING_BUFFER_SIZE
    )
    reading_debounce_seconds = config.get(
        CONF_READING_DEBOUNCE_SECONDS, DEFAULT_READING_DEBOUNCE_SECONDS
    )

    if not all([air_gap_sensor, tank_diameter, tank_length]):
        _LOGGER.error("Missing required configuration")
        return None, []

    coordinator = HeatingOilCoordinator(
        hass,
        air_gap_sensor,
        tank_diameter,
        tank_length,
        refill_threshold,
        noise_threshold,
        consumption_days,
        temperature_sensor,
        reference_temperature,
        refill_stabilization_minutes,
        refill_stability_threshold,
        reading_buffer_size,
        reading_debounce_seconds,
        entry_id=entry_id,
    )

    sensors: list[SensorEntity] = [
        HeatingOilVolumeSensor(coordinator),
        HeatingOilDailyConsumptionSensor(coordinator),
        HeatingOilDailyConsumptionEnergySensor(coordinator),
        HeatingOilMonthlyConsumptionSensor(coordinator),
        HeatingOilDaysUntilEmptySensor(coordinator),
        HeatingOilLastRefillSensor(coordinator),
        HeatingOilLastRefillVolumeSensor(coordinator),
    ]

    if temperature_sensor:
        sensors.append(HeatingOilNormalizedVolumeSensor(coordinator))

    return coordinator, sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    config = hass.data[DOMAIN][entry.entry_id]
    coordinator, sensors = _create_coordinator_and_sensors(hass, config, entry_id=entry.entry_id)
    if coordinator:
        hass.data[DOMAIN][entry.entry_id] = coordinator
    if sensors:
        async_add_entities(sensors, True)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor platform (YAML legacy support)."""
    if discovery_info is None:
        return
    coordinator, sensors = _create_coordinator_and_sensors(hass, discovery_info)
    if sensors:
        async_add_entities(sensors, True)


class HeatingOilVolumeSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for current heating oil volume."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Volume"
        self._attr_unique_id = f"{DOMAIN}_volume"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:oil"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )
        """Return the state of the sensor."""
        data = self.coordinator.data
        if data is None or data.volume is None:
            return None
        return round(data.volume, 2)

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        return data is not None and data.volume is not None

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self.coordinator.restore_volume(float(last_state.state))
            except (ValueError, TypeError):
                pass


class HeatingOilDailyConsumptionSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for average daily heating oil consumption over configured period."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Daily Consumption"
        self._attr_unique_id = f"{DOMAIN}_daily_consumption"
        self._attr_device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:chart-line"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )
        self._last_value: float = 0.0

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        data = self.coordinator.data
        value = 0.0 if data is None else data.daily_consumption
        self._last_value = value
        return round(value, 2)

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        return data is not None and data.volume is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "calculation_period_days": self.coordinator.consumption_days,
            "period_type": "rolling_average",
            "description": f"Average daily consumption over last {self.coordinator.consumption_days} days",
        }

        # Add information about the actual data period
        if self.coordinator.consumption_history:
            cutoff = dt_util.now() - timedelta(days=self.coordinator.consumption_days)
            recent = [
                entry
                for entry in self.coordinator.consumption_history
                if entry["timestamp"] > cutoff
            ]

            if recent:
                oldest_entry = min(recent, key=lambda x: x["timestamp"])
                days_in_period = (
                    dt_util.now() - oldest_entry["timestamp"]
                ).total_seconds() / 86400
                total_consumption = sum(e["consumption"] for e in recent)

                attrs["period_start"] = oldest_entry["timestamp"].isoformat()
                attrs["actual_days_of_data"] = round(days_in_period, 1)
                attrs["total_consumption_in_period"] = round(total_consumption, 2)
                attrs["data_points"] = len(recent)

        return attrs

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._last_value = float(last_state.state)
                _LOGGER.debug(
                    "Restored 'Daily Consumption' last value: %.2f L",
                    self._last_value,
                )
            except (ValueError, TypeError):
                pass


class HeatingOilDailyConsumptionEnergySensor(
    CoordinatorEntity, RestoreEntity, SensorEntity
):
    """Sensor for average daily heating oil energy consumption in kWh over configured period."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Daily Energy Consumption"
        self._attr_unique_id = f"{DOMAIN}_daily_consumption_kwh"
        self._attr_device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )
        self._last_value: float = 0.0

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        data = self.coordinator.data
        value = 0.0 if data is None else data.daily_consumption_kwh
        self._last_value = value
        return round(value, 2)

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        return data is not None and data.volume is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        daily_liters = self.coordinator.get_daily_consumption()

        attrs = {
            "conversion_factor": f"{KEROSENE_KWH_PER_LITER} kWh/L",
            "calculation_period_days": self.coordinator.consumption_days,
            "period_type": "rolling_average",
            "description": f"Average daily energy consumption over last {self.coordinator.consumption_days} days",
        }

        if daily_liters and daily_liters > 0:
            attrs["average_daily_consumption_liters"] = daily_liters

        # Add information about the actual data period
        if self.coordinator.consumption_history:
            cutoff = dt_util.now() - timedelta(days=self.coordinator.consumption_days)
            recent = [
                entry
                for entry in self.coordinator.consumption_history
                if entry["timestamp"] > cutoff
            ]

            if recent:
                oldest_entry = min(recent, key=lambda x: x["timestamp"])
                days_in_period = (
                    dt_util.now() - oldest_entry["timestamp"]
                ).total_seconds() / 86400

                attrs["period_start"] = oldest_entry["timestamp"].isoformat()
                attrs["actual_days_of_data"] = round(days_in_period, 1)
                attrs["data_points"] = len(recent)

        return attrs

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._last_value = float(last_state.state)
                _LOGGER.debug(
                    "Restored 'Daily Energy Consumption' last value: %.2f kWh",
                    self._last_value,
                )
            except (ValueError, TypeError):
                pass


class HeatingOilMonthlyConsumptionSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for monthly heating oil consumption (this month since 1st)."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Monthly Consumption"
        self._attr_unique_id = f"{DOMAIN}_monthly_consumption"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:chart-bar"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )
        self._last_value: float = 0.0

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        data = self.coordinator.data
        value = 0.0 if data is None else data.monthly_consumption
        self._last_value = value
        return round(value, 2)

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        return data is not None and data.volume is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        now = dt_util.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return {
            "period_start": month_start.isoformat(),
            "period_type": "current_month",
            "description": "Consumption since start of month",
        }

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._last_value = float(last_state.state)
                _LOGGER.debug(
                    "Restored 'Monthly Consumption' last value: %.2f L",
                    self._last_value,
                )
            except (ValueError, TypeError):
                pass


class HeatingOilDaysUntilEmptySensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for estimated days until tank is empty."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Days Until Empty"
        self._attr_unique_id = f"{DOMAIN}_days_until_empty"
        self._attr_native_unit_of_measurement = UnitOfTime.DAYS
        self._attr_icon = "mdi:calendar-clock"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )
        self._last_calculated_value: int | None = None

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        data = self.coordinator.data
        calculated_value = None if data is None else data.days_until_empty

        if calculated_value is not None:
            # We have a fresh calculation, store it
            self._last_calculated_value = calculated_value
            return calculated_value

        # No fresh calculation available, return last known value
        return self._last_calculated_value

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        if data is None or data.volume is None:
            return False
        return data.days_until_empty is not None or self._last_calculated_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}
        data = self.coordinator.data

        attrs["calculation_period_days"] = self.coordinator.consumption_days

        # Calculate average consumption for the period
        if self.coordinator.consumption_history:
            cutoff = dt_util.now() - timedelta(days=self.coordinator.consumption_days)
            recent = [
                entry["consumption"]
                for entry in self.coordinator.consumption_history
                if entry["timestamp"] > cutoff
            ]

            if recent:
                oldest_entry = min(
                    (
                        entry
                        for entry in self.coordinator.consumption_history
                        if entry["timestamp"] > cutoff
                    ),
                    key=lambda x: x["timestamp"],
                    default=None,
                )
                if oldest_entry:
                    days_in_period = (dt_util.now() - oldest_entry["timestamp"]).days
                    if days_in_period < 1:
                        days_in_period = 1

                    total_consumption = sum(recent)
                    average_daily = total_consumption / days_in_period

                    attrs["average_daily_consumption"] = round(average_daily, 2)
                    attrs["days_of_data"] = days_in_period

        # Add info about whether this is a live calculation or restored value
        if (data is None or data.days_until_empty is None) and self._last_calculated_value is not None:
            attrs["status"] = "Using last calculated value (no recent consumption data)"
        else:
            attrs["status"] = "Live calculation"

        return attrs

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in ("unknown", "unavailable"):
                try:
                    self._last_calculated_value = int(float(last_state.state))
                    _LOGGER.debug(
                        "Restored 'Days Until Empty' last value: %s days",
                        self._last_calculated_value,
                    )
                except (ValueError, TypeError):
                    pass


class HeatingOilLastRefillSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for last refill timestamp."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Last Refill"
        self._attr_unique_id = f"{DOMAIN}_last_refill"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_icon = "mdi:gas-station"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        data = self.coordinator.data
        return None if data is None else data.last_refill_date

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        return data is not None and data.last_refill_date is not None

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in ("unknown", "unavailable"):
                try:
                    self.coordinator.restore_last_refill(
                        dt_util.parse_datetime(last_state.state),
                        None,
                    )
                except (ValueError, TypeError):
                    pass


class HeatingOilLastRefillVolumeSensor(
    CoordinatorEntity, RestoreEntity, SensorEntity
):
    """Sensor for last refill volume."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Last Refill Volume"
        self._attr_unique_id = f"{DOMAIN}_last_refill_volume"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:gas-station"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        data = self.coordinator.data
        if data is None or data.last_refill_volume is None:
            return None
        return round(data.last_refill_volume, 2)

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        return data is not None and data.last_refill_volume is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}

        data = self.coordinator.data
        if data and data.last_refill_date:
            attrs["last_refill_date"] = data.last_refill_date.isoformat()

        # Add refill history
        if self.coordinator.refill_history:
            attrs["refill_count"] = len(self.coordinator.refill_history)
            attrs["total_refilled"] = round(
                sum(
                    entry["volume_added"]
                    for entry in self.coordinator.refill_history
                    if entry["volume_added"] is not None
                ),
                2,
            )

        return attrs

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                last_volume = float(last_state.state)
            except (ValueError, TypeError):
                last_volume = None

            # Restore last refill date from attributes
            last_refill_date = None
            if last_state.attributes.get("last_refill_date"):
                try:
                    last_refill_date = dt_util.parse_datetime(
                        last_state.attributes["last_refill_date"]
                    )
                except (ValueError, TypeError):
                    pass

            if last_volume is not None or last_refill_date is not None:
                self.coordinator.restore_last_refill(last_refill_date, last_volume)


class HeatingOilNormalizedVolumeSensor(
    CoordinatorEntity, RestoreEntity, SensorEntity
):
    """Sensor for temperature-normalized heating oil volume."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Heating Oil Normalized Volume"
        self._attr_unique_id = f"{DOMAIN}_normalized_volume"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:oil-temperature"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.air_gap_sensor)},
            name="Heating Oil Tank",
            manufacturer="Custom",
            model="Horizontal Cylinder",
        )

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        data = self.coordinator.data
        if data is None or data.normalized_volume is None:
            return None
        return round(data.normalized_volume, 2)

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        data = self.coordinator.data
        return (
            data is not None
            and data.volume is not None
            and self.coordinator.temperature_sensor is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "reference_temperature": self.coordinator.reference_temperature,
            "thermal_expansion_coefficient": f"{THERMAL_EXPANSION_COEFFICIENT:.5f}",
            "thermal_expansion_percent": f"{THERMAL_EXPANSION_COEFFICIENT * 100:.3f}%",
        }

        if self.coordinator.data and self.coordinator.data.volume is not None:
            attrs["measured_volume"] = self.coordinator.data.volume

        current_temp = self.coordinator.data.temperature if self.coordinator.data else None
        if current_temp is not None:
            attrs["current_temperature"] = current_temp

            # Calculate the temperature correction being applied
            if self.coordinator.data and self.coordinator.data.volume is not None:
                temp_diff = current_temp - self.coordinator.reference_temperature
                normalized = self.coordinator.get_normalized_volume()
                if normalized is not None:
                    volume_diff = self.coordinator.data.volume - normalized
                    attrs["temperature_difference"] = round(temp_diff, 2)
                    attrs["volume_correction"] = round(volume_diff, 2)
                    attrs["description"] = (
                        f"Volume normalized to {self.coordinator.reference_temperature}°C. "
                        f"Current temp: {current_temp}°C, "
                        f"Correction: {volume_diff:+.2f}L"
                    )
        else:
            attrs["description"] = "Temperature sensor unavailable"

        return attrs

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        # Note: We don't restore state here as the normalized volume
        # is always calculated from current volume and temperature
