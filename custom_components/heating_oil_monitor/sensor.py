"""Sensor platform for Heating Oil Monitor."""

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume, UnitOfTime, UnitOfEnergy
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_AIR_GAP_SENSOR,
    CONF_TANK_DIAMETER,
    CONF_TANK_LENGTH,
    CONF_REFILL_THRESHOLD,
    CONF_NOISE_THRESHOLD,
    CONF_CONSUMPTION_DAYS,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_CONSUMPTION_DAYS,
    KEROSENE_KWH_PER_LITER,
)

_LOGGER = logging.getLogger(__name__)


def calculate_volume(air_gap_cm: float, diameter_cm: float, length_cm: float) -> float:
    """Calculate volume in liters for horizontal cylindrical tank."""
    radius = diameter_cm / 2

    # Height of oil from bottom of tank
    liquid_height = diameter_cm - air_gap_cm

    # Handle edge cases
    if liquid_height <= 0:
        return 0.0
    if liquid_height >= diameter_cm:
        # Full tank
        return math.pi * radius**2 * length_cm / 1000

    # Circular segment area formula
    h = liquid_height
    r = radius

    # Area of circular segment
    area = r**2 * math.acos((r - h) / r) - (r - h) * math.sqrt(2 * r * h - h**2)

    # Volume in cm³, convert to liters
    volume_liters = (area * length_cm) / 1000

    return round(volume_liters, 2)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    config = hass.data[DOMAIN][entry.entry_id]

    air_gap_sensor = config.get(CONF_AIR_GAP_SENSOR)
    tank_diameter = config.get(CONF_TANK_DIAMETER)
    tank_length = config.get(CONF_TANK_LENGTH)
    refill_threshold = config.get(CONF_REFILL_THRESHOLD, DEFAULT_REFILL_THRESHOLD)
    noise_threshold = config.get(CONF_NOISE_THRESHOLD, DEFAULT_NOISE_THRESHOLD)
    consumption_days = config.get(CONF_CONSUMPTION_DAYS, DEFAULT_CONSUMPTION_DAYS)

    if not all([air_gap_sensor, tank_diameter, tank_length]):
        _LOGGER.error("Missing required configuration")
        return

    coordinator = HeatingOilCoordinator(
        hass,
        air_gap_sensor,
        tank_diameter,
        tank_length,
        refill_threshold,
        noise_threshold,
        consumption_days,
    )

    sensors = [
        HeatingOilVolumeSensor(coordinator),
        HeatingOilDailyConsumptionSensor(coordinator),
        HeatingOilDailyConsumptionEnergySensor(coordinator),  # NEW SENSOR
        HeatingOilMonthlyConsumptionSensor(coordinator),
        HeatingOilDaysUntilEmptySensor(coordinator),
        HeatingOilLastRefillSensor(coordinator),
        HeatingOilLastRefillVolumeSensor(coordinator),
    ]

    async_add_entities(sensors, True)


# Keep backward compatibility with YAML platform setup
async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor platform (YAML legacy support)."""
    if discovery_info is None:
        return

    air_gap_sensor = discovery_info.get(CONF_AIR_GAP_SENSOR)
    tank_diameter = discovery_info.get(CONF_TANK_DIAMETER)
    tank_length = discovery_info.get(CONF_TANK_LENGTH)
    refill_threshold = discovery_info.get(
        CONF_REFILL_THRESHOLD, DEFAULT_REFILL_THRESHOLD
    )
    noise_threshold = discovery_info.get(CONF_NOISE_THRESHOLD, DEFAULT_NOISE_THRESHOLD)
    consumption_days = discovery_info.get(
        CONF_CONSUMPTION_DAYS, DEFAULT_CONSUMPTION_DAYS
    )

    if not all([air_gap_sensor, tank_diameter, tank_length]):
        _LOGGER.error("Missing required configuration")
        return

    coordinator = HeatingOilCoordinator(
        hass,
        air_gap_sensor,
        tank_diameter,
        tank_length,
        refill_threshold,
        noise_threshold,
        consumption_days,
    )

    sensors = [
        HeatingOilVolumeSensor(coordinator),
        HeatingOilDailyConsumptionSensor(coordinator),
        HeatingOilDailyConsumptionEnergySensor(coordinator),  # NEW SENSOR
        HeatingOilMonthlyConsumptionSensor(coordinator),
        HeatingOilDaysUntilEmptySensor(coordinator),
        HeatingOilLastRefillSensor(coordinator),
        HeatingOilLastRefillVolumeSensor(coordinator),
    ]

    async_add_entities(sensors, True)


class HeatingOilCoordinator:
    """Coordinator to manage heating oil data."""

    def __init__(
        self,
        hass: HomeAssistant,
        air_gap_sensor: str,
        tank_diameter: float,
        tank_length: float,
        refill_threshold: float,
        noise_threshold: float,
        consumption_days: int,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.air_gap_sensor = air_gap_sensor
        self.tank_diameter = tank_diameter
        self.tank_length = tank_length
        self.refill_threshold = refill_threshold
        self.noise_threshold = noise_threshold
        self.consumption_days = consumption_days

        self._current_volume: float | None = None
        self._previous_volume: float | None = None
        self._last_refill_date: datetime | None = None
        self._last_refill_volume: float | None = None
        self._refill_history: list[dict] = []
        self._consumption_history: list[dict] = []
        self._listeners: list = []

        # Subscribe to air gap sensor changes
        async_track_state_change_event(
            hass, [air_gap_sensor], self._handle_air_gap_change
        )

        # Subscribe to manual refill events
        hass.bus.async_listen(f"{DOMAIN}_refill", self._handle_manual_refill)

    @callback
    async def _handle_air_gap_change(self, event: Event) -> None:
        """Handle air gap sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        try:
            air_gap = float(new_state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(f"Invalid air gap value: {new_state.state}")
            return

        new_volume = calculate_volume(air_gap, self.tank_diameter, self.tank_length)

        await self._process_volume_reading(new_volume)

    async def _process_volume_reading(self, new_volume: float) -> None:
        """Process a new volume reading with filtering logic."""
        if self._current_volume is None:
            # First reading
            self._current_volume = new_volume
            self._previous_volume = new_volume
            _LOGGER.info(f"Initial volume reading: {new_volume} L")
            self._notify_listeners()
            return

        volume_change = new_volume - self._current_volume

        # Check for refill (significant increase)
        if volume_change > self.refill_threshold:
            refill_volume = volume_change
            _LOGGER.info(
                f"Refill detected: {refill_volume:.2f} L added "
                f"({self._current_volume:.2f} → {new_volume:.2f} L)"
            )
            await self._record_refill(new_volume, refill_volume)
            return

        # Ignore small increases (noise/temperature)
        if volume_change > 0 and volume_change < self.noise_threshold:
            _LOGGER.debug(f"Ignoring small increase: {volume_change:.2f} cm")
            return

        # Ignore unexpected increases
        if volume_change > 0:
            _LOGGER.warning(
                f"Unexpected volume increase ignored: {volume_change:.2f} L "
                f"(below refill threshold)"
            )
            return

        # Valid decrease (consumption)
        if volume_change < 0:
            consumption = abs(volume_change)
            self._record_consumption(consumption)
            self._previous_volume = self._current_volume
            self._current_volume = new_volume
            _LOGGER.debug(
                f"Consumption: {consumption:.2f} L, New volume: {new_volume:.2f} L"
            )
            self._notify_listeners()

    async def _record_refill(
        self, new_volume: float, refill_volume: float | None = None
    ) -> None:
        """Record a refill event with date and volume."""
        refill_date = dt_util.now()

        # If refill_volume not provided, calculate it
        if refill_volume is None and self._current_volume is not None:
            refill_volume = new_volume - self._current_volume

        self._last_refill_date = refill_date
        self._last_refill_volume = refill_volume
        self._previous_volume = self._current_volume
        self._current_volume = new_volume

        # Add to refill history
        refill_record = {
            "timestamp": refill_date,
            "volume_added": refill_volume,
            "total_volume": new_volume,
        }
        self._refill_history.append(refill_record)

        # Keep only last 12 months of refill history
        cutoff = dt_util.now() - timedelta(days=365)
        self._refill_history = [
            entry for entry in self._refill_history if entry["timestamp"] > cutoff
        ]

        # Clear old consumption history
        self._consumption_history = []

        _LOGGER.info(
            f"Refill recorded: {refill_volume:.2f} L added on {refill_date}, "
            f"new total: {new_volume:.2f} L"
        )
        self._notify_listeners()

    @callback
    async def _handle_manual_refill(self, event: Event) -> None:
        """Handle manual refill service call."""
        volume = event.data.get("volume")

        if volume:
            # Volume provided - this is the amount ADDED, not total
            if self._current_volume is not None:
                new_total = self._current_volume + volume
                await self._record_refill(new_total, volume)
            else:
                # No current volume, treat as total
                await self._record_refill(volume, volume)
        else:
            # No volume provided - just mark refill at current reading
            # Calculate what was added based on tank capacity assumption
            if self._current_volume is not None:
                # Assume tank was refilled to current level from previous level
                refill_amount = None  # We don't know how much was added
                self._last_refill_date = dt_util.now()
                self._last_refill_volume = refill_amount
                self._refill_history.append(
                    {
                        "timestamp": self._last_refill_date,
                        "volume_added": None,
                        "total_volume": self._current_volume,
                    }
                )
                self._consumption_history = []
                _LOGGER.info(
                    f"Manual refill marked at {self._last_refill_date}, "
                    f"current volume: {self._current_volume:.2f} L (volume added unknown)"
                )
                self._notify_listeners()

    def _record_consumption(self, consumption: float) -> None:
        """Record consumption with timestamp."""
        self._consumption_history.append(
            {
                "timestamp": dt_util.now(),
                "consumption": consumption,
            }
        )

        # Keep only last 60 days of history
        cutoff = dt_util.now() - timedelta(days=60)
        self._consumption_history = [
            entry for entry in self._consumption_history if entry["timestamp"] > cutoff
        ]

    def get_daily_consumption(self) -> float | None:
        """Calculate average daily consumption."""
        if not self._consumption_history:
            return None

        cutoff = dt_util.now() - timedelta(days=1)
        recent = [
            entry["consumption"]
            for entry in self._consumption_history
            if entry["timestamp"] > cutoff
        ]

        return round(sum(recent), 2) if recent else None

    def get_daily_consumption_kwh(self) -> float | None:
        """Calculate daily energy consumption in kWh."""
        daily_liters = self.get_daily_consumption()
        if daily_liters is None:
            return None

        # Convert liters to kWh using kerosene energy content
        kwh = daily_liters * KEROSENE_KWH_PER_LITER
        return round(kwh, 2)

    def get_monthly_consumption(self) -> float | None:
        """Calculate average monthly consumption."""
        if not self._consumption_history:
            return None

        cutoff = dt_util.now() - timedelta(days=30)
        recent = [
            entry["consumption"]
            for entry in self._consumption_history
            if entry["timestamp"] > cutoff
        ]

        return round(sum(recent), 2) if recent else None

    def get_days_until_empty(self) -> int | None:
        """Estimate days until tank is empty based on recent consumption."""
        if self._current_volume is None or self._current_volume <= 0:
            return 0

        if not self._consumption_history:
            return None

        # Calculate average daily consumption over the configured period
        cutoff = dt_util.now() - timedelta(days=self.consumption_days)
        recent = [
            entry["consumption"]
            for entry in self._consumption_history
            if entry["timestamp"] > cutoff
        ]

        if not recent:
            return None

        # Calculate actual days in the period (in case we have less than consumption_days of data)
        if self._consumption_history:
            oldest_entry = min(
                (
                    entry
                    for entry in self._consumption_history
                    if entry["timestamp"] > cutoff
                ),
                key=lambda x: x["timestamp"],
                default=None,
            )
            if oldest_entry:
                days_in_period = (dt_util.now() - oldest_entry["timestamp"]).days
                if days_in_period < 1:
                    days_in_period = 1  # Minimum 1 day
            else:
                days_in_period = 1
        else:
            days_in_period = 1

        total_consumption = sum(recent)
        average_daily = total_consumption / days_in_period

        if average_daily <= 0:
            return None

        return int(self._current_volume / average_daily)

    def add_listener(self, listener) -> None:
        """Add a listener for updates."""
        self._listeners.append(listener)

    def _notify_listeners(self) -> None:
        """Notify all listeners of an update."""
        for listener in self._listeners:
            listener()


class HeatingOilVolumeSensor(RestoreEntity, SensorEntity):
    """Sensor for current heating oil volume."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Volume"
        self._attr_unique_id = f"{DOMAIN}_volume"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:oil"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator._current_volume

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._coordinator._current_volume = float(last_state.state)
                self._coordinator._previous_volume = float(last_state.state)
            except (ValueError, TypeError):
                pass


class HeatingOilDailyConsumptionSensor(SensorEntity):
    """Sensor for daily heating oil consumption."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Daily Consumption"
        self._attr_unique_id = f"{DOMAIN}_daily_consumption"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:chart-line"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator.get_daily_consumption()


class HeatingOilDailyConsumptionEnergySensor(SensorEntity):
    """Sensor for daily heating oil energy consumption in kWh."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Daily Energy Consumption"
        self._attr_unique_id = f"{DOMAIN}_daily_consumption_kwh"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = "mdi:lightning-bolt"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator.get_daily_consumption_kwh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}
        attrs["conversion_factor"] = f"{KEROSENE_KWH_PER_LITER} kWh/L"

        daily_liters = self._coordinator.get_daily_consumption()
        if daily_liters:
            attrs["daily_consumption_liters"] = daily_liters

        return attrs


class HeatingOilMonthlyConsumptionSensor(SensorEntity):
    """Sensor for monthly heating oil consumption."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Monthly Consumption"
        self._attr_unique_id = f"{DOMAIN}_monthly_consumption"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:chart-bar"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator.get_monthly_consumption()


class HeatingOilDaysUntilEmptySensor(SensorEntity):
    """Sensor for estimated days until tank is empty."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Days Until Empty"
        self._attr_unique_id = f"{DOMAIN}_days_until_empty"
        self._attr_native_unit_of_measurement = UnitOfTime.DAYS
        self._attr_icon = "mdi:calendar-clock"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        return self._coordinator.get_days_until_empty()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}

        attrs["calculation_period_days"] = self._coordinator.consumption_days

        # Calculate average consumption for the period
        if self._coordinator._consumption_history:
            cutoff = dt_util.now() - timedelta(days=self._coordinator.consumption_days)
            recent = [
                entry["consumption"]
                for entry in self._coordinator._consumption_history
                if entry["timestamp"] > cutoff
            ]

            if recent:
                oldest_entry = min(
                    (
                        entry
                        for entry in self._coordinator._consumption_history
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

        return attrs


class HeatingOilLastRefillSensor(RestoreEntity, SensorEntity):
    """Sensor for last refill timestamp."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Last Refill"
        self._attr_unique_id = f"{DOMAIN}_last_refill"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_icon = "mdi:gas-station"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        return self._coordinator._last_refill_date

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in ("unknown", "unavailable"):
                try:
                    self._coordinator._last_refill_date = dt_util.parse_datetime(
                        last_state.state
                    )
                except (ValueError, TypeError):
                    pass


class HeatingOilLastRefillVolumeSensor(RestoreEntity, SensorEntity):
    """Sensor for last refill volume."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Last Refill Volume"
        self._attr_unique_id = f"{DOMAIN}_last_refill_volume"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:gas-station"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator._last_refill_volume

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}

        if self._coordinator._last_refill_date:
            attrs["last_refill_date"] = self._coordinator._last_refill_date.isoformat()

        # Add refill history
        if self._coordinator._refill_history:
            attrs["refill_count"] = len(self._coordinator._refill_history)
            attrs["total_refilled"] = round(
                sum(
                    entry["volume_added"]
                    for entry in self._coordinator._refill_history
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
                self._coordinator._last_refill_volume = float(last_state.state)
            except (ValueError, TypeError):
                pass

            # Restore last refill date from attributes
            if last_state.attributes.get("last_refill_date"):
                try:
                    self._coordinator._last_refill_date = dt_util.parse_datetime(
                        last_state.attributes["last_refill_date"]
                    )
                except (ValueError, TypeError):
                    pass
