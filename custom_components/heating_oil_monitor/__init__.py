"""Heating Oil Monitor Integration."""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

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
)
from .coordinator import HeatingOilCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# Keep YAML config support for backward compatibility
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_AIR_GAP_SENSOR): cv.entity_id,
                vol.Required(CONF_TANK_DIAMETER): cv.positive_int,
                vol.Required(CONF_TANK_LENGTH): cv.positive_int,
                vol.Optional(
                    CONF_REFILL_THRESHOLD, default=DEFAULT_REFILL_THRESHOLD
                ): cv.positive_int,
                vol.Optional(
                    CONF_NOISE_THRESHOLD, default=DEFAULT_NOISE_THRESHOLD
                ): cv.positive_float,
                vol.Optional(
                    CONF_CONSUMPTION_DAYS, default=DEFAULT_CONSUMPTION_DAYS
                ): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Heating Oil Monitor component from YAML."""
    hass.data.setdefault(DOMAIN, {})

    # Register service for manual refill
    async def handle_record_refill(call: ServiceCall) -> None:
        """Handle the record_refill service call."""
        volume = call.data.get("volume")
        entry_id = call.data.get("entry_id")
        _LOGGER.info("Manual refill recorded. Volume: %s", volume)

        # Resolve target coordinator(s)
        coordinators: list[HeatingOilCoordinator] = []
        if entry_id:
            coord = hass.data[DOMAIN].get(entry_id)
            if isinstance(coord, HeatingOilCoordinator):
                coordinators.append(coord)
            else:
                _LOGGER.warning("No coordinator found for entry_id: %s", entry_id)
        else:
            coordinators = [
                c
                for c in hass.data[DOMAIN].values()
                if isinstance(c, HeatingOilCoordinator)
            ]

        for coord in coordinators:
            await coord.async_record_refill(volume)

    hass.services.async_register(
        DOMAIN,
        "record_refill",
        handle_record_refill,
        schema=vol.Schema(
            {
                vol.Optional("volume"): cv.positive_float,
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )

    # Support YAML configuration (legacy)
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=config[DOMAIN],
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Oil Monitor from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Merge entry.data and entry.options (options take precedence)
    config = {**entry.data, **entry.options}

    air_gap_sensor = config.get(CONF_AIR_GAP_SENSOR)
    tank_diameter = config.get(CONF_TANK_DIAMETER)
    tank_length = config.get(CONF_TANK_LENGTH)

    if not all([air_gap_sensor, tank_diameter, tank_length]):
        _LOGGER.error("Missing required configuration for entry %s", entry.entry_id)
        return False

    coordinator = HeatingOilCoordinator(
        hass,
        air_gap_sensor=air_gap_sensor,
        tank_diameter=tank_diameter,
        tank_length=tank_length,
        refill_threshold=config.get(CONF_REFILL_THRESHOLD, DEFAULT_REFILL_THRESHOLD),
        noise_threshold=config.get(CONF_NOISE_THRESHOLD, DEFAULT_NOISE_THRESHOLD),
        consumption_days=config.get(CONF_CONSUMPTION_DAYS, DEFAULT_CONSUMPTION_DAYS),
        temperature_sensor=config.get(CONF_TEMPERATURE_SENSOR),
        reference_temperature=config.get(
            CONF_REFERENCE_TEMPERATURE, DEFAULT_REFERENCE_TEMPERATURE
        ),
        refill_stabilization_minutes=config.get(
            CONF_REFILL_STABILIZATION_MINUTES,
            DEFAULT_REFILL_STABILIZATION_MINUTES,
        ),
        refill_stability_threshold=config.get(
            CONF_REFILL_STABILITY_THRESHOLD,
            DEFAULT_REFILL_STABILITY_THRESHOLD,
        ),
        reading_buffer_size=config.get(
            CONF_READING_BUFFER_SIZE, DEFAULT_READING_BUFFER_SIZE
        ),
        reading_debounce_seconds=config.get(
            CONF_READING_DEBOUNCE_SECONDS, DEFAULT_READING_DEBOUNCE_SECONDS
        ),
        entry_id=entry.entry_id,
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
