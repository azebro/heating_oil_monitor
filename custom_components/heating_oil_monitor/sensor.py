"""Sensor platform for My Integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""
    coordinator = MyIntegrationCoordinator(hass, entry)
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Add sensors
    async_add_entities(
        [
            MyIntegrationSensor(coordinator, entry),
            MyIntegrationStatusSensor(coordinator, entry),
        ]
    )


class MyIntegrationCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.host = entry.data.get("host")
        self.api_key = entry.data.get("api_key")
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        """Update data via API."""
        # TODO: Fetch data from your API here
        # For now, return dummy data
        _LOGGER.debug("Fetching data from %s", self.host)
        
        return {
            "value": 42,
            "status": "online",
            "last_update": "2025-01-07T12:00:00Z",
        }


class MyIntegrationSensor(CoordinatorEntity, SensorEntity):
    """My Integration Sensor."""

    def __init__(self, coordinator: MyIntegrationCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "My Integration Value"
        self._attr_unique_id = f"{entry.entry_id}_value"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("value")
        return None


class MyIntegrationStatusSensor(CoordinatorEntity, SensorEntity):
    """My Integration Status Sensor."""

    def __init__(self, coordinator: MyIntegrationCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "My Integration Status"
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("status")
        return "unknown"