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
    CONF_TEMPERATURE_SENSOR,
    CONF_REFERENCE_TEMPERATURE,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_CONSUMPTION_DAYS,
    DEFAULT_REFERENCE_TEMPERATURE,
    KEROSENE_KWH_PER_LITER,
    THERMAL_EXPANSION_COEFFICIENT,
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


def apply_thermal_compensation(
    measured_volume: float,
    current_temp: float | None,
    reference_temp: float,
) -> float:
    """
    Apply thermal expansion compensation to measured volume.

    Converts measured volume at current temperature to equivalent volume
    at reference temperature. This normalizes for thermal expansion/contraction.

    Args:
        measured_volume: Volume measured at current temperature (liters)
        current_temp: Current temperature (°C), None if unavailable
        reference_temp: Reference temperature for normalization (°C)

    Returns:
        Temperature-normalized volume at reference temperature (liters)
    """
    if current_temp is None:
        # No temperature sensor, return measured volume
        return measured_volume

    # Calculate temperature difference
    temp_diff = current_temp - reference_temp

    # Apply thermal expansion correction
    # V_ref = V_measured / (1 + α × ΔT)
    # This converts current volume to what it would be at reference temperature
    correction_factor = 1 + (THERMAL_EXPANSION_COEFFICIENT * temp_diff)

    normalized_volume = measured_volume / correction_factor

    return round(normalized_volume, 2)


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
    temperature_sensor = config.get(CONF_TEMPERATURE_SENSOR)
    reference_temperature = config.get(
        CONF_REFERENCE_TEMPERATURE, DEFAULT_REFERENCE_TEMPERATURE
    )

    _LOGGER.info(
        f"Setup config: temperature_sensor={temperature_sensor}, "
        f"reference_temperature={reference_temperature}, "
        f"all config keys={list(config.keys())}"
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
        temperature_sensor,
        reference_temperature,
    )

    sensors = [
        HeatingOilVolumeSensor(coordinator),
        HeatingOilDailyConsumptionSensor(coordinator),
        HeatingOilDailyConsumptionEnergySensor(coordinator),
        HeatingOilMonthlyConsumptionSensor(coordinator),
        HeatingOilDaysUntilEmptySensor(coordinator),
        HeatingOilLastRefillSensor(coordinator),
        HeatingOilLastRefillVolumeSensor(coordinator),
    ]

    # Add normalized volume sensor if temperature sensor is configured
    if temperature_sensor:
        _LOGGER.info(
            f"Adding normalized volume sensor with temperature sensor: {temperature_sensor}"
        )
        sensors.append(HeatingOilNormalizedVolumeSensor(coordinator))
    else:
        _LOGGER.info(
            "No temperature sensor configured, normalized volume sensor will not be added"
        )

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
    temperature_sensor = discovery_info.get(CONF_TEMPERATURE_SENSOR)
    reference_temperature = discovery_info.get(
        CONF_REFERENCE_TEMPERATURE, DEFAULT_REFERENCE_TEMPERATURE
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
        temperature_sensor,
        reference_temperature,
    )

    sensors = [
        HeatingOilVolumeSensor(coordinator),
        HeatingOilDailyConsumptionSensor(coordinator),
        HeatingOilDailyConsumptionEnergySensor(coordinator),
        HeatingOilMonthlyConsumptionSensor(coordinator),
        HeatingOilDaysUntilEmptySensor(coordinator),
        HeatingOilLastRefillSensor(coordinator),
        HeatingOilLastRefillVolumeSensor(coordinator),
    ]

    # Add normalized volume sensor if temperature sensor is configured
    if temperature_sensor:
        sensors.append(HeatingOilNormalizedVolumeSensor(coordinator))

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
        temperature_sensor: str | None = None,
        reference_temperature: float = DEFAULT_REFERENCE_TEMPERATURE,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.air_gap_sensor = air_gap_sensor
        self.tank_diameter = tank_diameter
        self.tank_length = tank_length
        self.refill_threshold = refill_threshold
        self.noise_threshold = noise_threshold
        self.consumption_days = consumption_days
        self.temperature_sensor = temperature_sensor
        self.reference_temperature = reference_temperature

        self._current_volume: float | None = None
        self._previous_volume: float | None = None
        self._current_temperature: float | None = None
        self._last_refill_date: datetime | None = None
        self._last_refill_volume: float | None = None
        self._refill_history: list[dict] = []
        self._consumption_history: list[dict] = []
        self._listeners: list = []

        # Subscribe to air gap sensor changes
        async_track_state_change_event(
            hass, [air_gap_sensor], self._handle_air_gap_change
        )

        # Subscribe to temperature sensor changes if configured
        if temperature_sensor:
            async_track_state_change_event(
                hass, [temperature_sensor], self._handle_temperature_change
            )

        # Subscribe to manual refill events
        hass.bus.async_listen(f"{DOMAIN}_refill", self._handle_manual_refill)

        # Initialize volume from current sensor reading
        self._initialize_volume()

        # Initialize temperature from current sensor reading
        if temperature_sensor:
            self._initialize_temperature()

        # Restore consumption history from database
        hass.async_create_task(self._restore_consumption_history())

    def _initialize_volume(self) -> None:
        """Initialize volume from current air gap sensor reading."""
        state = self.hass.states.get(self.air_gap_sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                air_gap = float(state.state)
                self._current_volume = calculate_volume(
                    air_gap, self.tank_diameter, self.tank_length
                )
                self._previous_volume = self._current_volume
                _LOGGER.info(
                    f"Initialized volume from sensor: {self._current_volume} L"
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(f"Could not initialize volume from sensor: {e}")

    def _initialize_temperature(self) -> None:
        """Initialize temperature from current temperature sensor reading."""
        if not self.temperature_sensor:
            return

        state = self.hass.states.get(self.temperature_sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._current_temperature = float(state.state)
                _LOGGER.info(
                    f"Initialized temperature from sensor: {self._current_temperature} °C"
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning(f"Could not initialize temperature from sensor: {e}")

    @callback
    async def _handle_temperature_change(self, event: Event) -> None:
        """Handle temperature sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        try:
            self._current_temperature = float(new_state.state)
            _LOGGER.debug(f"Temperature updated: {self._current_temperature} °C")
            # Notify listeners so normalized volume sensor updates
            self._notify_listeners()
        except (ValueError, TypeError):
            _LOGGER.warning(f"Invalid temperature value: {new_state.state}")
            return

    def get_normalized_volume(self) -> float | None:
        """Get temperature-compensated volume at reference temperature."""
        if self._current_volume is None:
            return None

        return apply_thermal_compensation(
            self._current_volume,
            self._current_temperature,
            self.reference_temperature,
        )

    async def _restore_consumption_history(self) -> None:
        """Restore consumption history from Home Assistant recorder."""
        try:
            from homeassistant.components.recorder import get_instance

            # Get the recorder instance
            recorder = get_instance(self.hass)
            if not recorder or not recorder.engine:
                _LOGGER.warning(
                    "Recorder not available, cannot restore consumption history"
                )
                return

            # Try to find the volume sensor entity_id
            possible_entity_ids = [
                "sensor.heating_oil_volume",
                f"sensor.{DOMAIN}_volume",
            ]

            volume_sensor_id = None
            for entity_id in possible_entity_ids:
                if self.hass.states.get(entity_id):
                    volume_sensor_id = entity_id
                    _LOGGER.info(f"Found volume sensor: {volume_sensor_id}")
                    break

            if not volume_sensor_id:
                _LOGGER.warning(
                    f"Could not find volume sensor. Tried: {possible_entity_ids}. "
                    f"Available sensors: {[s for s in self.hass.states.async_entity_ids() if 'heating_oil' in s]}"
                )
                return

            # Get historical states for the last 60 days
            end_time = dt_util.now()
            start_time = end_time - timedelta(days=60)

            _LOGGER.info(
                f"Attempting to restore consumption history for {volume_sensor_id} "
                f"from {start_time} to {end_time}"
            )

            # Query the recorder for historical states
            from homeassistant.components.recorder.history import (
                state_changes_during_period,
            )

            states = await recorder.async_add_executor_job(
                state_changes_during_period,
                self.hass,
                start_time,
                end_time,
                volume_sensor_id,
                False,
                False,
                1000,  # limit
            )

            if not states or volume_sensor_id not in states:
                _LOGGER.info(
                    f"No historical states found for {volume_sensor_id}. "
                    f"This is normal if the sensor was just created."
                )
                return

            # Process states to rebuild consumption history
            volume_states = states[volume_sensor_id]
            _LOGGER.info(f"Found {len(volume_states)} historical states")

            previous_volume = None
            consumption_count = 0

            for idx, state in enumerate(volume_states):
                if state.state in ("unknown", "unavailable"):
                    continue

                try:
                    current_volume = float(state.state)

                    if previous_volume is not None:
                        volume_change = current_volume - previous_volume

                        # Only record decreases (consumption) that are not refills
                        if (
                            volume_change < 0
                            and abs(volume_change) < self.refill_threshold
                        ):
                            consumption = abs(volume_change)

                            # Add to consumption history
                            self._consumption_history.append(
                                {
                                    "timestamp": state.last_updated,
                                    "consumption": consumption,
                                }
                            )
                            consumption_count += 1

                    previous_volume = current_volume

                except (ValueError, TypeError) as e:
                    _LOGGER.debug(f"Error processing state {idx}: {e}")
                    continue

            # Keep only entries from last 60 days
            cutoff = dt_util.now() - timedelta(days=60)
            self._consumption_history = [
                entry
                for entry in self._consumption_history
                if entry["timestamp"] > cutoff
            ]

            _LOGGER.info(
                f"✓ HISTORY RESTORED: {len(self._consumption_history)} consumption entries "
                f"from last 60 days (processed {len(volume_states)} states)"
            )

            # Log today's consumption
            today_midnight = dt_util.start_of_local_day()
            today_entries = [
                entry
                for entry in self._consumption_history
                if entry["timestamp"] >= today_midnight
            ]
            today_total = sum(e["consumption"] for e in today_entries)

            _LOGGER.info(
                f"Today's data: {len(today_entries)} entries, Total: {today_total:.2f} L"
            )

            # Trigger update of all sensors
            self._notify_listeners()

        except Exception as e:
            _LOGGER.error(f"Error restoring consumption history: {e}", exc_info=True)

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

        _LOGGER.debug(
            f"Volume change detected: {volume_change:.2f} L "
            f"({self._current_volume:.2f} → {new_volume:.2f} L)"
        )

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
            _LOGGER.debug(f"Ignoring small increase: {volume_change:.2f} L")
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

        _LOGGER.info(
            f"Consumption recorded: {consumption:.2f} L, "
            f"Total history entries: {len(self._consumption_history)}"
        )

        # Keep only last 60 days of history
        cutoff = dt_util.now() - timedelta(days=60)
        self._consumption_history = [
            entry for entry in self._consumption_history if entry["timestamp"] > cutoff
        ]

    def get_daily_consumption(self) -> float:
        """Calculate average daily consumption over configured period."""
        if not self._consumption_history:
            return 0.0

        # Get consumption data for the configured period
        cutoff = dt_util.now() - timedelta(days=self.consumption_days)
        recent = [
            entry["consumption"]
            for entry in self._consumption_history
            if entry["timestamp"] > cutoff
        ]

        if not recent:
            return 0.0

        # Calculate actual days in the period to get accurate average
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
            days_in_period = (
                dt_util.now() - oldest_entry["timestamp"]
            ).total_seconds() / 86400
            if days_in_period < 0.1:  # Less than ~2.4 hours
                days_in_period = 0.1
        else:
            days_in_period = 1.0

        total_consumption = sum(recent)
        average_daily = total_consumption / days_in_period

        return round(average_daily, 2)

    def get_daily_consumption_kwh(self) -> float:
        """Calculate average daily energy consumption in kWh."""
        daily_liters = self.get_daily_consumption()

        # Convert liters to kWh using kerosene energy content
        kwh = daily_liters * KEROSENE_KWH_PER_LITER
        return round(kwh, 2)

    def get_monthly_consumption(self) -> float:
        """Calculate consumption for current month (since start of month)."""
        if not self._consumption_history:
            return 0.0

        # Get first day of current month at midnight
        now = dt_util.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Sum all consumption since start of month
        month_consumption = [
            entry["consumption"]
            for entry in self._consumption_history
            if entry["timestamp"] >= month_start
        ]

        return round(sum(month_consumption), 2) if month_consumption else 0.0

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

        # Calculate actual days in the period
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
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:oil"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator._current_volume

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self._coordinator._current_volume is not None

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._coordinator._current_volume = float(last_state.state)
                self._coordinator._previous_volume = float(last_state.state)
            except (ValueError, TypeError):
                pass


class HeatingOilDailyConsumptionSensor(RestoreEntity, SensorEntity):
    """Sensor for average daily heating oil consumption over configured period."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Daily Consumption"
        self._attr_unique_id = f"{DOMAIN}_daily_consumption"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:chart-line"
        self._last_value: float = 0.0

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        value = self._coordinator.get_daily_consumption()
        self._last_value = value
        return value

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self._coordinator._current_volume is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "calculation_period_days": self._coordinator.consumption_days,
            "period_type": "rolling_average",
            "description": f"Average daily consumption over last {self._coordinator.consumption_days} days",
        }

        # Add information about the actual data period
        if self._coordinator._consumption_history:
            cutoff = dt_util.now() - timedelta(days=self._coordinator.consumption_days)
            recent = [
                entry
                for entry in self._coordinator._consumption_history
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
                _LOGGER.info(
                    f"Restored 'Daily Consumption' last value: {self._last_value} L"
                )
            except (ValueError, TypeError):
                pass


class HeatingOilDailyConsumptionEnergySensor(RestoreEntity, SensorEntity):
    """Sensor for average daily heating oil energy consumption in kWh over configured period."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Daily Energy Consumption"
        self._attr_unique_id = f"{DOMAIN}_daily_consumption_kwh"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = "mdi:lightning-bolt"
        self._last_value: float = 0.0

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        value = self._coordinator.get_daily_consumption_kwh()
        self._last_value = value
        return value

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self._coordinator._current_volume is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        daily_liters = self._coordinator.get_daily_consumption()

        attrs = {
            "conversion_factor": f"{KEROSENE_KWH_PER_LITER} kWh/L",
            "calculation_period_days": self._coordinator.consumption_days,
            "period_type": "rolling_average",
            "description": f"Average daily energy consumption over last {self._coordinator.consumption_days} days",
        }

        if daily_liters and daily_liters > 0:
            attrs["average_daily_consumption_liters"] = daily_liters

        # Add information about the actual data period
        if self._coordinator._consumption_history:
            cutoff = dt_util.now() - timedelta(days=self._coordinator.consumption_days)
            recent = [
                entry
                for entry in self._coordinator._consumption_history
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
                _LOGGER.info(
                    f"Restored 'Daily Energy Consumption' last value: {self._last_value} kWh"
                )
            except (ValueError, TypeError):
                pass


class HeatingOilMonthlyConsumptionSensor(RestoreEntity, SensorEntity):
    """Sensor for monthly heating oil consumption (this month since 1st)."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Monthly Consumption"
        self._attr_unique_id = f"{DOMAIN}_monthly_consumption"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:chart-bar"
        self._last_value: float = 0.0

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        value = self._coordinator.get_monthly_consumption()
        self._last_value = value
        return value

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self._coordinator._current_volume is not None

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
                _LOGGER.info(
                    f"Restored 'Monthly Consumption' last value: {self._last_value} L"
                )
            except (ValueError, TypeError):
                pass


class HeatingOilDaysUntilEmptySensor(RestoreEntity, SensorEntity):
    """Sensor for estimated days until tank is empty."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Days Until Empty"
        self._attr_unique_id = f"{DOMAIN}_days_until_empty"
        self._attr_native_unit_of_measurement = UnitOfTime.DAYS
        self._attr_icon = "mdi:calendar-clock"
        self._last_calculated_value: int | None = None

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        # Try to get current calculation
        calculated_value = self._coordinator.get_days_until_empty()

        if calculated_value is not None:
            # We have a fresh calculation, store it
            self._last_calculated_value = calculated_value
            return calculated_value

        # No fresh calculation available, return last known value
        return self._last_calculated_value

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        # Available if we have a volume reading and either:
        # - Current calculation is possible, OR
        # - We have a last known value
        return self._coordinator._current_volume is not None and (
            self._coordinator.get_days_until_empty() is not None
            or self._last_calculated_value is not None
        )

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

        # Add info about whether this is a live calculation or restored value
        if (
            self._coordinator.get_days_until_empty() is None
            and self._last_calculated_value is not None
        ):
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
                    _LOGGER.info(
                        f"Restored 'Days Until Empty' last value: {self._last_calculated_value} days"
                    )
                except (ValueError, TypeError):
                    pass


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

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self._coordinator._last_refill_date is not None

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
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:gas-station"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator._last_refill_volume

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self._coordinator._last_refill_volume is not None

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


class HeatingOilNormalizedVolumeSensor(RestoreEntity, SensorEntity):
    """Sensor for temperature-normalized heating oil volume."""

    def __init__(self, coordinator: HeatingOilCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_name = "Heating Oil Normalized Volume"
        self._attr_unique_id = f"{DOMAIN}_normalized_volume"
        self._attr_device_class = SensorDeviceClass.VOLUME
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
        self._attr_icon = "mdi:oil-temperature"

        coordinator.add_listener(self.async_write_ha_state)

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self._coordinator.get_normalized_volume()

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return (
            self._coordinator._current_volume is not None
            and self._coordinator.temperature_sensor is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "reference_temperature": self._coordinator.reference_temperature,
            "thermal_expansion_coefficient": f"{THERMAL_EXPANSION_COEFFICIENT:.5f}",
            "thermal_expansion_percent": f"{THERMAL_EXPANSION_COEFFICIENT * 100:.3f}%",
        }

        if self._coordinator._current_volume is not None:
            attrs["measured_volume"] = self._coordinator._current_volume

        if self._coordinator._current_temperature is not None:
            attrs["current_temperature"] = self._coordinator._current_temperature

            # Calculate the temperature correction being applied
            if self._coordinator._current_volume is not None:
                temp_diff = (
                    self._coordinator._current_temperature
                    - self._coordinator.reference_temperature
                )
                volume_diff = self._coordinator._current_volume - self.native_value
                attrs["temperature_difference"] = round(temp_diff, 2)
                attrs["volume_correction"] = round(volume_diff, 2)
                attrs["description"] = (
                    f"Volume normalized to {self._coordinator.reference_temperature}°C. "
                    f"Current temp: {self._coordinator._current_temperature}°C, "
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
