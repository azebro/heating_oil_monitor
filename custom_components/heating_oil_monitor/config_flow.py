"""Config flow for Heating Oil Monitor integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

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

_LOGGER = logging.getLogger(__name__)


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the shared schema for config and options flows."""
    return vol.Schema(
        {
            vol.Required(
                CONF_AIR_GAP_SENSOR,
                default=defaults.get(CONF_AIR_GAP_SENSOR),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_TANK_DIAMETER,
                default=defaults.get(CONF_TANK_DIAMETER, 150),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=500,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
                )
            ),
            vol.Required(
                CONF_TANK_LENGTH,
                default=defaults.get(CONF_TANK_LENGTH, 200),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=1000,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="cm",
                )
            ),
            vol.Optional(
                CONF_REFILL_THRESHOLD,
                default=defaults.get(CONF_REFILL_THRESHOLD, DEFAULT_REFILL_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=10000,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="L",
                )
            ),
            vol.Optional(
                CONF_NOISE_THRESHOLD,
                default=defaults.get(CONF_NOISE_THRESHOLD, DEFAULT_NOISE_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=0.1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="L",
                )
            ),
            vol.Optional(
                CONF_CONSUMPTION_DAYS,
                default=defaults.get(CONF_CONSUMPTION_DAYS, DEFAULT_CONSUMPTION_DAYS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=90,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="days",
                )
            ),
            vol.Optional(
                CONF_TEMPERATURE_SENSOR,
                default=defaults.get(CONF_TEMPERATURE_SENSOR),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_REFERENCE_TEMPERATURE,
                default=defaults.get(
                    CONF_REFERENCE_TEMPERATURE, DEFAULT_REFERENCE_TEMPERATURE
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-50,
                    max=50,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ),
            vol.Optional(
                CONF_REFILL_STABILIZATION_MINUTES,
                default=defaults.get(
                    CONF_REFILL_STABILIZATION_MINUTES,
                    DEFAULT_REFILL_STABILIZATION_MINUTES,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5,
                    max=180,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Optional(
                CONF_REFILL_STABILITY_THRESHOLD,
                default=defaults.get(
                    CONF_REFILL_STABILITY_THRESHOLD,
                    DEFAULT_REFILL_STABILITY_THRESHOLD,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=50,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="L",
                )
            ),
            vol.Optional(
                CONF_READING_BUFFER_SIZE,
                default=defaults.get(
                    CONF_READING_BUFFER_SIZE,
                    DEFAULT_READING_BUFFER_SIZE,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=3,
                    max=20,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_READING_DEBOUNCE_SECONDS,
                default=defaults.get(
                    CONF_READING_DEBOUNCE_SECONDS,
                    DEFAULT_READING_DEBOUNCE_SECONDS,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=300,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="sec",
                )
            ),
        }
    )


class HeatingOilMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heating Oil Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate that the sensor exists
            if not self.hass.states.get(user_input[CONF_AIR_GAP_SENSOR]):
                errors[CONF_AIR_GAP_SENSOR] = "sensor_not_found"
            else:
                # Check if already configured
                await self.async_set_unique_id(user_input[CONF_AIR_GAP_SENSOR])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Heating Oil Monitor",
                    data=user_input,
                )

        data_schema = _build_schema({
            CONF_TANK_DIAMETER: 150,
            CONF_TANK_LENGTH: 200,
            CONF_REFILL_THRESHOLD: DEFAULT_REFILL_THRESHOLD,
            CONF_NOISE_THRESHOLD: DEFAULT_NOISE_THRESHOLD,
            CONF_CONSUMPTION_DAYS: DEFAULT_CONSUMPTION_DAYS,
            CONF_REFERENCE_TEMPERATURE: DEFAULT_REFERENCE_TEMPERATURE,
            CONF_REFILL_STABILIZATION_MINUTES: DEFAULT_REFILL_STABILIZATION_MINUTES,
            CONF_REFILL_STABILITY_THRESHOLD: DEFAULT_REFILL_STABILITY_THRESHOLD,
            CONF_READING_BUFFER_SIZE: DEFAULT_READING_BUFFER_SIZE,
            CONF_READING_DEBOUNCE_SECONDS: DEFAULT_READING_DEBOUNCE_SECONDS,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_import(self, import_config: dict[str, Any]) -> FlowResult:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(import_config)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return HeatingOilMonitorOptionsFlow()


class HeatingOilMonitorOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Heating Oil Monitor."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update the config entry with new data
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **user_input},
            )
            return self.async_create_entry(title="", data={})

        data_schema = _build_schema({
            CONF_AIR_GAP_SENSOR: self.config_entry.data.get(CONF_AIR_GAP_SENSOR),
            CONF_TANK_DIAMETER: self.config_entry.data.get(CONF_TANK_DIAMETER, 150),
            CONF_TANK_LENGTH: self.config_entry.data.get(CONF_TANK_LENGTH, 200),
            CONF_REFILL_THRESHOLD: self.config_entry.data.get(CONF_REFILL_THRESHOLD, DEFAULT_REFILL_THRESHOLD),
            CONF_NOISE_THRESHOLD: self.config_entry.data.get(CONF_NOISE_THRESHOLD, DEFAULT_NOISE_THRESHOLD),
            CONF_CONSUMPTION_DAYS: self.config_entry.data.get(CONF_CONSUMPTION_DAYS, DEFAULT_CONSUMPTION_DAYS),
            CONF_TEMPERATURE_SENSOR: self.config_entry.data.get(CONF_TEMPERATURE_SENSOR),
            CONF_REFERENCE_TEMPERATURE: self.config_entry.data.get(CONF_REFERENCE_TEMPERATURE, DEFAULT_REFERENCE_TEMPERATURE),
            CONF_REFILL_STABILIZATION_MINUTES: self.config_entry.data.get(CONF_REFILL_STABILIZATION_MINUTES, DEFAULT_REFILL_STABILIZATION_MINUTES),
            CONF_REFILL_STABILITY_THRESHOLD: self.config_entry.data.get(CONF_REFILL_STABILITY_THRESHOLD, DEFAULT_REFILL_STABILITY_THRESHOLD),
            CONF_READING_BUFFER_SIZE: self.config_entry.data.get(CONF_READING_BUFFER_SIZE, DEFAULT_READING_BUFFER_SIZE),
            CONF_READING_DEBOUNCE_SECONDS: self.config_entry.data.get(CONF_READING_DEBOUNCE_SECONDS, DEFAULT_READING_DEBOUNCE_SECONDS),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )
