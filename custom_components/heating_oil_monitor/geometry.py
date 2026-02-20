"""Geometry utilities for heating oil tanks."""

from __future__ import annotations

import math


def calculate_volume(air_gap_cm: float, diameter_cm: float, length_cm: float) -> float:
    """Calculate oil volume (liters) for a horizontal cylindrical tank.

    No rounding is applied here; rounding must be done at sensor output only.
    """
    if diameter_cm <= 0 or length_cm <= 0:
        return 0.0
    if air_gap_cm < 0:
        air_gap_cm = 0.0

    radius = diameter_cm / 2
    liquid_height = diameter_cm - air_gap_cm

    if liquid_height <= 0:
        return 0.0

    if liquid_height >= diameter_cm:
        return math.pi * radius**2 * length_cm / 1000.0

    h = liquid_height
    r = radius

    area = (
        r**2 * math.acos((r - h) / r)
        - (r - h) * math.sqrt(2 * r * h - h**2)
    )

    return (area * length_cm) / 1000.0
