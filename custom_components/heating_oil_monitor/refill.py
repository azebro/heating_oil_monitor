"""Refill detection and stabilization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RefillStabilizer:
    """Track refill stabilization and determine stable refill volume."""

    refill_threshold: float
    stabilization_minutes: int
    stability_threshold: float
    in_progress: bool = False
    start_time: datetime | None = None
    buffer: list[dict] = field(default_factory=list)
    pre_refill_volume: float | None = None

    def start(self, new_volume: float, now: datetime, current_volume: float | None) -> None:
        """Start a refill stabilization period."""
        self.in_progress = True
        self.start_time = now
        self.pre_refill_volume = current_volume
        self.buffer = [{"timestamp": now, "volume": new_volume}]

    def add_reading(self, new_volume: float, now: datetime) -> None:
        """Add a new reading to the stabilization buffer."""
        self.buffer.append({"timestamp": now, "volume": new_volume})

    def minutes_elapsed(self, now: datetime) -> float:
        """Get minutes elapsed since refill start."""
        if self.start_time is None:
            return 0.0
        return (now - self.start_time).total_seconds() / 60

    def should_finalize(self, now: datetime) -> bool:
        """Return True if stabilization period should be finalized."""
        if self.minutes_elapsed(now) >= self.stabilization_minutes:
            return True
        return len(self.buffer) >= 5 and self.is_stable()

    def is_stable(self) -> bool:
        """Check if recent readings are stable (low variance)."""
        if len(self.buffer) < 5:
            return False

        recent_volumes = [r["volume"] for r in self.buffer[-5:]]
        max_diff = max(recent_volumes) - min(recent_volumes)
        return max_diff <= self.stability_threshold

    def stable_volume(self, fallback_volume: float | None) -> float:
        """Return a stable volume using median of recent readings."""
        if not self.buffer:
            return fallback_volume or 0.0

        recent_volumes = [r["volume"] for r in self.buffer[-5:]]
        sorted_volumes = sorted(recent_volumes)
        mid = len(sorted_volumes) // 2

        if len(sorted_volumes) % 2 == 0:
            return (sorted_volumes[mid - 1] + sorted_volumes[mid]) / 2

        return sorted_volumes[mid]

    def reset(self) -> None:
        """Reset stabilization state."""
        self.in_progress = False
        self.start_time = None
        self.buffer = []
        self.pre_refill_volume = None
