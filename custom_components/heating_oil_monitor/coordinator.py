"""Coordinator for Heating Oil Monitor data and updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
    DEFAULT_CONSUMPTION_DAYS,
    DEFAULT_CONSUMPTION_HISTORY_DAYS,
    DEFAULT_REFILL_HISTORY_MAX,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_REFILL_STABILIZATION_MINUTES,
    DEFAULT_REFILL_STABILITY_THRESHOLD,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_READING_BUFFER_SIZE,
    DEFAULT_READING_DEBOUNCE_SECONDS,
    DEFAULT_REFERENCE_TEMPERATURE,
    KEROSENE_KWH_PER_LITER,
)
from .consumption import ConsumptionTracker
from .geometry import calculate_volume
from .refill import RefillStabilizer
from .thermal import normalize_volume

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeatingOilData:
    """Snapshot of heating oil data for sensors."""

    volume: float | None
    normalized_volume: float | None
    temperature: float | None
    daily_consumption: float
    daily_consumption_kwh: float
    monthly_consumption: float
    days_until_empty: int | None
    last_refill_date: datetime | None
    last_refill_volume: float | None


class HeatingOilCoordinator(DataUpdateCoordinator[HeatingOilData]):
    """Coordinator to manage heating oil data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        air_gap_sensor: str,
        tank_diameter: float,
        tank_length: float,
        refill_threshold: float = DEFAULT_REFILL_THRESHOLD,
        noise_threshold: float = DEFAULT_NOISE_THRESHOLD,
        consumption_days: int = DEFAULT_CONSUMPTION_DAYS,
        temperature_sensor: str | None = None,
        reference_temperature: float = DEFAULT_REFERENCE_TEMPERATURE,
        refill_stabilization_minutes: int = DEFAULT_REFILL_STABILIZATION_MINUTES,
        refill_stability_threshold: float = DEFAULT_REFILL_STABILITY_THRESHOLD,
        reading_buffer_size: int = DEFAULT_READING_BUFFER_SIZE,
        reading_debounce_seconds: int = DEFAULT_READING_DEBOUNCE_SECONDS,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, _LOGGER, name=DOMAIN)

        self.hass = hass
        self.air_gap_sensor = air_gap_sensor
        self.tank_diameter = tank_diameter
        self.tank_length = tank_length
        self.refill_threshold = refill_threshold
        self.noise_threshold = noise_threshold
        self.consumption_days = consumption_days
        self.temperature_sensor = temperature_sensor
        self.reference_temperature = reference_temperature
        self.refill_stabilization_minutes = refill_stabilization_minutes
        self.refill_stability_threshold = refill_stability_threshold
        self.reading_buffer_size = reading_buffer_size
        self.reading_debounce_seconds = reading_debounce_seconds

        self._current_volume: float | None = None
        self._previous_volume: float | None = None
        self._current_temperature: float | None = None
        self._last_refill_date: datetime | None = None
        self._last_refill_volume: float | None = None
        self._refill_history: list[dict] = []

        self._consumption = ConsumptionTracker(
            consumption_days=consumption_days,
            max_history_days=DEFAULT_CONSUMPTION_HISTORY_DAYS,
        )

        storage_key = f"{STORAGE_KEY}_{entry_id}" if entry_id else STORAGE_KEY
        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._history_loaded: bool = False
        self._history_load_task = hass.async_create_task(self._async_load_history())

        self._refill = RefillStabilizer(
            refill_threshold=refill_threshold,
            stabilization_minutes=refill_stabilization_minutes,
            stability_threshold=refill_stability_threshold,
        )

        self._reading_buffer: list[dict] = []
        self._last_processed_time: datetime | None = None

        async_track_state_change_event(
            hass, [air_gap_sensor], self._handle_air_gap_change
        )

        if temperature_sensor:
            async_track_state_change_event(
                hass, [temperature_sensor], self._handle_temperature_change
            )

        self._initialize_volume()

        if temperature_sensor:
            self._initialize_temperature()

        self._publish()

        hass.async_create_task(self._restore_consumption_history())

    async def _async_update_data(self) -> HeatingOilData:
        """Provide data for coordinator refresh requests."""
        self._publish()
        return self.data

    @property
    def consumption_history(self) -> list[dict]:
        """Return consumption history entries."""
        return self._consumption.get_history_entries()

    @property
    def refill_history(self) -> list[dict]:
        """Return refill history entries."""
        return self._refill_history

    def _schedule_save(self) -> None:
        """Schedule saving history to storage."""
        self._store.async_delay_save(self._serialize_history, 10)

    def _serialize_history(self) -> dict:
        """Serialize history state for persistence."""
        return {
            "version": STORAGE_VERSION,
            "consumption_daily": self._consumption.get_daily_totals(),
            "refill_history": self._refill_history,
            "last_refill": {
                "timestamp": (
                    self._last_refill_date.isoformat()
                    if self._last_refill_date
                    else None
                ),
                "volume": self._last_refill_volume,
            },
        }

    async def _async_load_history(self) -> None:
        """Load persisted history from storage."""
        data = await self._store.async_load()
        if not data:
            return

        if data.get("version") != STORAGE_VERSION:
            _LOGGER.debug("History schema version mismatch; ignoring persisted data")
            return

        daily_totals = data.get("consumption_daily", {})
        if isinstance(daily_totals, dict):
            self._consumption.set_daily_totals(daily_totals)

        refill_history = data.get("refill_history", [])
        if isinstance(refill_history, list):
            self._refill_history = refill_history[-DEFAULT_REFILL_HISTORY_MAX:]

        last_refill = data.get("last_refill") or {}
        if isinstance(last_refill, dict):
            ts = last_refill.get("timestamp")
            if ts:
                try:
                    self._last_refill_date = dt_util.parse_datetime(ts)
                except (TypeError, ValueError):
                    self._last_refill_date = None
            self._last_refill_volume = last_refill.get("volume")

        self._history_loaded = True
        self._publish()

    def restore_volume(self, volume: float) -> None:
        """Restore the last known volume from entity state."""
        self._current_volume = volume
        self._previous_volume = volume
        self._publish()

    def restore_last_refill(
        self, refill_date: datetime | None, volume: float | None
    ) -> None:
        """Restore last refill values from entity state."""
        self._last_refill_date = refill_date
        self._last_refill_volume = volume
        self._publish()
        self._schedule_save()

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
                _LOGGER.debug(
                    "Initialized volume from sensor: %.2f L", self._current_volume
                )
            except (ValueError, TypeError) as exc:
                _LOGGER.debug("Could not initialize volume from sensor: %s", exc)

    def _initialize_temperature(self) -> None:
        """Initialize temperature from current temperature sensor reading."""
        if not self.temperature_sensor:
            return

        state = self.hass.states.get(self.temperature_sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._current_temperature = float(state.state)
                _LOGGER.debug(
                    "Initialized temperature from sensor: %.2f °C",
                    self._current_temperature,
                )
            except (ValueError, TypeError) as exc:
                _LOGGER.debug("Could not initialize temperature from sensor: %s", exc)

    async def _handle_temperature_change(self, event: Event) -> None:
        """Handle temperature sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        try:
            self._current_temperature = float(new_state.state)
            _LOGGER.debug("Temperature updated: %.2f °C", self._current_temperature)
            self._publish()
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid temperature value: %s", new_state.state)

    async def _handle_air_gap_change(self, event: Event) -> None:
        """Handle air gap sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        try:
            air_gap = float(new_state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid air gap value: %s", new_state.state)
            return

        new_volume = calculate_volume(air_gap, self.tank_diameter, self.tank_length)
        await self._process_volume_reading(new_volume)

    def _get_median_volume(self, readings: list[dict]) -> float:
        """Calculate median volume from a list of readings."""
        if not readings:
            return 0.0

        volumes = [r["volume"] for r in readings]
        sorted_volumes = sorted(volumes)
        mid = len(sorted_volumes) // 2

        if len(sorted_volumes) % 2 == 0:
            return (sorted_volumes[mid - 1] + sorted_volumes[mid]) / 2
        return sorted_volumes[mid]

    def _should_process_reading(self, now: datetime) -> bool:
        """Check if enough time has passed since last processed reading."""
        if self._last_processed_time is None:
            return True

        elapsed = (now - self._last_processed_time).total_seconds()
        return elapsed >= self.reading_debounce_seconds

    async def _process_volume_reading(self, new_volume: float) -> None:
        """Process a new volume reading with median filtering, debouncing, and refill stabilization."""
        now = dt_util.now()

        self._reading_buffer.append({"timestamp": now, "volume": new_volume})

        cutoff = now - timedelta(minutes=5)
        buffer_size = int(self.reading_buffer_size)
        self._reading_buffer = [
            r for r in self._reading_buffer if r["timestamp"] > cutoff
        ][-max(buffer_size * 2, 10) :]

        if self._current_volume is None:
            if len(self._reading_buffer) >= buffer_size:
                median_volume = self._get_median_volume(
                    self._reading_buffer[-buffer_size:]
                )
                self._current_volume = median_volume
                self._previous_volume = median_volume
                self._last_processed_time = now
                _LOGGER.debug(
                    "Initial volume reading (median of %s): %.2f L",
                    buffer_size,
                    median_volume,
                )
                self._publish()
            elif len(self._reading_buffer) == 1:
                self._current_volume = new_volume
                self._previous_volume = new_volume
                self._last_processed_time = now
                _LOGGER.debug("Initial volume reading: %.2f L", new_volume)
                self._publish()
            return

        if self._refill.in_progress:
            await self._handle_refill_stabilization(new_volume, now)
            return

        raw_change = new_volume - self._current_volume
        if raw_change > self.refill_threshold:
            await self._start_refill_stabilization(new_volume, now)
            return

        if not self._should_process_reading(now):
            _LOGGER.debug(
                "Debouncing: skipping reading %.2f L (last processed %.0fs ago)",
                new_volume,
                (now - self._last_processed_time).total_seconds(),
            )
            return

        if len(self._reading_buffer) >= buffer_size:
            filtered_volume = self._get_median_volume(
                self._reading_buffer[-buffer_size:]
            )
        else:
            filtered_volume = new_volume

        volume_change = filtered_volume - self._current_volume

        _LOGGER.debug(
            "Volume change (filtered): %.2f L (%.2f → %.2f L), raw reading: %.2f L",
            volume_change,
            self._current_volume,
            filtered_volume,
            new_volume,
        )

        if volume_change > 0 and abs(volume_change) < self.noise_threshold:
            _LOGGER.debug("Ignoring small increase: %.2f L", volume_change)
            return

        if volume_change > 0:
            _LOGGER.warning(
                "Unexpected volume increase ignored: %.2f L (below refill threshold)",
                volume_change,
            )
            return

        if volume_change < 0 and abs(volume_change) >= 0.1:
            consumption = abs(volume_change)
            self._record_consumption(consumption)
            self._previous_volume = self._current_volume
            self._current_volume = filtered_volume
            self._last_processed_time = now
            _LOGGER.debug(
                "Consumption: %.2f L, New volume: %.2f L",
                consumption,
                filtered_volume,
            )
            self._publish()

    async def _start_refill_stabilization(
        self, new_volume: float, now: datetime
    ) -> None:
        """Start refill stabilization period."""
        self._refill.start(new_volume, now, self._current_volume)

        _LOGGER.info(
            "Refill detected - starting %s minute stabilization. Pre-refill: %.2f L, First: %.2f L",
            self.refill_stabilization_minutes,
            self._refill.pre_refill_volume or 0.0,
            new_volume,
        )

    async def _handle_refill_stabilization(
        self, new_volume: float, now: datetime
    ) -> None:
        """Handle readings during refill stabilization period."""
        self._refill.add_reading(new_volume, now)

        minutes_elapsed = self._refill.minutes_elapsed(now)
        _LOGGER.debug(
            "Refill stabilization: %.1f/%s min, buffer size: %s, latest: %.2f L",
            minutes_elapsed,
            self.refill_stabilization_minutes,
            len(self._refill.buffer),
            new_volume,
        )

        if self._refill.should_finalize(now):
            if len(self._refill.buffer) >= 5 and self._refill.is_stable():
                _LOGGER.info(
                    "Readings stabilized early after %.1f minutes", minutes_elapsed
                )
            await self._finalize_refill()

    async def _finalize_refill(self) -> None:
        """Finalize refill with stable reading."""
        stable_volume = self._refill.stable_volume(self._current_volume)
        refill_volume = stable_volume - (self._refill.pre_refill_volume or 0)

        _LOGGER.info(
            "Refill stabilized: %.2f L added (%.2f → %.2f L). Processed %s readings over %.1f minutes",
            refill_volume,
            self._refill.pre_refill_volume or 0.0,
            stable_volume,
            len(self._refill.buffer),
            (dt_util.now() - (self._refill.start_time or dt_util.now())).total_seconds()
            / 60,
        )

        self._refill.reset()
        await self._record_refill(stable_volume, refill_volume)

    async def _record_refill(
        self, new_volume: float, refill_volume: float | None = None
    ) -> None:
        """Record a refill event with date and volume."""
        refill_date = dt_util.now()

        if refill_volume is None and self._current_volume is not None:
            refill_volume = new_volume - self._current_volume

        self._last_refill_date = refill_date
        self._last_refill_volume = refill_volume
        self._previous_volume = self._current_volume
        self._current_volume = new_volume

        refill_record = {
            "timestamp": refill_date.isoformat(),
            "volume_added": refill_volume,
            "total_volume": new_volume,
        }
        self._refill_history.append(refill_record)

        cutoff = dt_util.now() - timedelta(days=365)
        self._refill_history = [
            entry for entry in self._refill_history
            if dt_util.parse_datetime(entry["timestamp"]) > cutoff
        ]
        if len(self._refill_history) > DEFAULT_REFILL_HISTORY_MAX:
            self._refill_history = self._refill_history[-DEFAULT_REFILL_HISTORY_MAX:]

        _LOGGER.info(
            "Refill recorded: %.2f L added on %s, new total: %.2f L",
            refill_volume or 0.0,
            refill_date,
            new_volume,
        )
        self._publish()
        self._schedule_save()

    async def async_record_refill(self, volume: float | None = None) -> None:
        """Record a manual refill.

        Called directly by the service handler. If *volume* is provided
        (liters added), it is added to the current volume. Otherwise
        the refill is marked with an unknown amount.
        """
        if volume:
            if self._current_volume is not None:
                new_total = self._current_volume + volume
                await self._record_refill(new_total, volume)
            else:
                await self._record_refill(volume, volume)
        else:
            if self._current_volume is not None:
                refill_amount = None
                self._last_refill_date = dt_util.now()
                self._last_refill_volume = refill_amount
                self._refill_history.append(
                    {
                        "timestamp": self._last_refill_date.isoformat(),
                        "volume_added": None,
                        "total_volume": self._current_volume,
                    }
                )
                _LOGGER.info(
                    "Manual refill marked at %s, current volume: %.2f L (volume added unknown)",
                    self._last_refill_date,
                    self._current_volume,
                )
                self._publish()
                self._schedule_save()

    def _record_consumption(self, consumption: float) -> None:
        """Record consumption with timestamp."""
        now = dt_util.now()
        self._consumption.record(consumption, now)
        _LOGGER.debug(
            "Consumption recorded: %.2f L, Total history entries: %s",
            consumption,
            len(self._consumption.get_history_entries()),
        )
        self._schedule_save()

    def get_daily_consumption(self) -> float:
        """Return average daily consumption over configured period."""
        return self._consumption.get_daily_consumption(dt_util.now())

    def get_daily_consumption_kwh(self) -> float:
        """Return average daily energy consumption in kWh."""
        daily_liters = self.get_daily_consumption()
        return daily_liters * KEROSENE_KWH_PER_LITER

    def get_monthly_consumption(self) -> float:
        """Return consumption for current month."""
        return self._consumption.get_monthly_consumption(dt_util.now())

    def get_days_until_empty(self) -> int | None:
        """Estimate days until tank is empty based on recent consumption."""
        return self._consumption.get_days_until_empty(
            dt_util.now(), self._current_volume
        )

    def get_normalized_volume(self) -> float | None:
        """Return temperature-compensated volume at reference temperature."""
        if self._current_volume is None:
            return None
        return normalize_volume(
            self._current_volume, self._current_temperature, self.reference_temperature
        )

    def _publish(self) -> None:
        """Publish updated data to listeners."""
        now = dt_util.now()
        daily_consumption = self._consumption.get_daily_consumption(now)
        daily_kwh = daily_consumption * KEROSENE_KWH_PER_LITER
        monthly_consumption = self._consumption.get_monthly_consumption(now)

        data = HeatingOilData(
            volume=self._current_volume,
            normalized_volume=self.get_normalized_volume(),
            temperature=self._current_temperature,
            daily_consumption=daily_consumption,
            daily_consumption_kwh=daily_kwh,
            monthly_consumption=monthly_consumption,
            days_until_empty=self._consumption.get_days_until_empty(
                now, self._current_volume
            ),
            last_refill_date=self._last_refill_date,
            last_refill_volume=self._last_refill_volume,
        )

        self.async_set_updated_data(data)

    async def _restore_consumption_history(self) -> None:
        """Restore consumption history from recorder database."""
        if self._history_load_task:
            await self._history_load_task
        if self._history_loaded:
            return
        try:
            from homeassistant.components.recorder import get_instance

            recorder = get_instance(self.hass)

            volume_sensor_id = None
            possible_entity_ids = [
                f"sensor.{DOMAIN}_volume",
                "sensor.heating_oil_volume",
                "sensor.heating_oil_monitor_volume",
            ]

            for entity_id in possible_entity_ids:
                if self.hass.states.get(entity_id) is not None:
                    volume_sensor_id = entity_id
                    _LOGGER.debug("Found volume sensor: %s", volume_sensor_id)
                    break

            if not volume_sensor_id:
                _LOGGER.warning(
                    "Could not find volume sensor. Tried: %s",
                    possible_entity_ids,
                )
                return

            end_time = dt_util.now()
            start_time = end_time - timedelta(days=60)

            _LOGGER.debug(
                "Restoring consumption history for %s from %s to %s",
                volume_sensor_id,
                start_time,
                end_time,
            )

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
                1000,
            )

            if not states or volume_sensor_id not in states:
                _LOGGER.debug(
                    "No historical states found for %s. This is normal if the sensor was just created.",
                    volume_sensor_id,
                )
                return

            volume_states = states[volume_sensor_id]
            _LOGGER.debug("Found %s historical states", len(volume_states))

            previous_volume = None

            for idx, state in enumerate(volume_states):
                if state.state in ("unknown", "unavailable"):
                    continue

                try:
                    current_volume = float(state.state)

                    if previous_volume is not None:
                        volume_change = current_volume - previous_volume

                        if (
                            volume_change < 0
                            and abs(volume_change) < self.refill_threshold
                        ):
                            consumption = abs(volume_change)
                            self._consumption.record(
                                consumption,
                                state.last_updated,
                                prune_at=dt_util.now(),
                            )

                    previous_volume = current_volume

                except (ValueError, TypeError) as exc:
                    _LOGGER.debug("Error processing state %s: %s", idx, exc)
                    continue

            _LOGGER.debug(
                "History restored: %s consumption entries",
                len(self._consumption.get_history_entries()),
            )

            self._publish()
            self._schedule_save()

        except Exception as exc:  # pragma: no cover - defensive logging
            _LOGGER.error("Error restoring consumption history: %s", exc, exc_info=True)
