"""Thermal compensation utilities for heating oil volume."""

from __future__ import annotations

from .const import THERMAL_EXPANSION_COEFFICIENT


def normalize_volume(
    measured_volume: float,
    current_temp: float | None,
    reference_temp: float,
) -> float:
    """Normalize measured volume to a reference temperature.

    No rounding is applied here; rounding must be done at sensor output only.
    """
    if current_temp is None:
        return measured_volume

    temp_diff = current_temp - reference_temp
    correction_factor = 1 + (THERMAL_EXPANSION_COEFFICIENT * temp_diff)

    return measured_volume / correction_factor
