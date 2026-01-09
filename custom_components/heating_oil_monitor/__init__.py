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
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_NOISE_THRESHOLD,
    DEFAULT_CONSUMPTION_DAYS,
)

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
        _LOGGER.info(f"Manual refill recorded. Volume: {volume}")

        # Dispatch event for sensor to handle
        hass.bus.async_fire(f"{DOMAIN}_refill", {"volume": volume})

    hass.services.async_register(
        DOMAIN,
        "record_refill",
        handle_record_refill,
        schema=vol.Schema(
            {
                vol.Optional("volume"): cv.positive_float,
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
    hass.data[DOMAIN][entry.entry_id] = entry.data

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
