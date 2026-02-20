"""Consumption tracking utilities for heating oil."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from homeassistant.util import dt as dt_util


@dataclass
class ConsumptionTracker:
    """Track consumption history and compute aggregates."""

    consumption_days: int
    max_history_days: int
    _daily_totals: dict[str, float] = field(default_factory=dict)

    def record(
        self,
        consumption: float,
        timestamp: datetime,
        *,
        prune_at: datetime | None = None,
    ) -> None:
        """Record a consumption entry and prune old data."""
        day_key = dt_util.as_local(timestamp).date().isoformat()
        self._daily_totals[day_key] = self._daily_totals.get(day_key, 0.0) + consumption
        self._prune(prune_at or timestamp)

    def clear(self) -> None:
        """Clear consumption history."""
        self._daily_totals = {}

    def _prune(self, now: datetime) -> None:
        """Keep only entries within max_history_days."""
        cutoff_date = dt_util.as_local(now).date() - timedelta(
            days=self.max_history_days
        )
        self._daily_totals = {
            day: total
            for day, total in self._daily_totals.items()
            if date.fromisoformat(day) > cutoff_date
        }

    def set_daily_totals(self, daily_totals: dict[str, float]) -> None:
        """Set daily totals from persisted storage."""
        self._daily_totals = dict(daily_totals)

    def get_daily_totals(self) -> dict[str, float]:
        """Return daily totals mapping."""
        return dict(self._daily_totals)

    def get_history_entries(self) -> list[dict]:
        """Return history entries for sensor attributes."""
        entries: list[dict] = []
        for day, total in self._daily_totals.items():
            day_date = date.fromisoformat(day)
            timestamp = dt_util.as_local(
                datetime.combine(day_date, datetime.max.time())
            )
            entries.append({"timestamp": timestamp, "consumption": total})

        return sorted(entries, key=lambda x: x["timestamp"])

    def get_daily_consumption(self, now: datetime) -> float:
        """Calculate average daily consumption over configured period."""
        if not self._daily_totals:
            return 0.0

        local_now = dt_util.as_local(now)
        cutoff_date = local_now.date() - timedelta(days=self.consumption_days)
        recent = [
            total
            for day, total in self._daily_totals.items()
            if date.fromisoformat(day) > cutoff_date
        ]

        if not recent:
            return 0.0

        recent_days = [
            date.fromisoformat(day)
            for day in self._daily_totals
            if date.fromisoformat(day) > cutoff_date
        ]
        oldest_day = min(recent_days) if recent_days else None

        if oldest_day:
            oldest_dt = dt_util.as_local(
                datetime.combine(oldest_day, datetime.min.time())
            )
            days_in_period = (local_now - oldest_dt).total_seconds() / 86400
            if days_in_period < 0.1:
                days_in_period = 0.1
        else:
            days_in_period = 1.0

        total_consumption = sum(recent)
        return total_consumption / days_in_period

    def get_monthly_consumption(self, now: datetime) -> float:
        """Calculate consumption for current month (since start of month)."""
        if not self._daily_totals:
            return 0.0

        month_start = dt_util.as_local(now).date().replace(day=1)
        month_consumption = [
            total
            for day, total in self._daily_totals.items()
            if date.fromisoformat(day) >= month_start
        ]

        return sum(month_consumption) if month_consumption else 0.0

    def get_days_until_empty(
        self, now: datetime, current_volume: float | None
    ) -> int | None:
        """Estimate days until tank is empty based on recent consumption."""
        if current_volume is None or current_volume <= 0:
            return 0

        if not self._daily_totals:
            return None

        local_now = dt_util.as_local(now)
        cutoff_date = local_now.date() - timedelta(days=self.consumption_days)
        recent = [
            total
            for day, total in self._daily_totals.items()
            if date.fromisoformat(day) > cutoff_date
        ]

        if not recent:
            return None

        recent_days = [
            date.fromisoformat(day)
            for day in self._daily_totals
            if date.fromisoformat(day) > cutoff_date
        ]
        oldest_day = min(recent_days) if recent_days else None

        if oldest_day:
            oldest_dt = dt_util.as_local(
                datetime.combine(oldest_day, datetime.min.time())
            )
            days_in_period = (local_now - oldest_dt).days
            if days_in_period < 1:
                days_in_period = 1
        else:
            days_in_period = 1

        total_consumption = sum(recent)
        average_daily = total_consumption / days_in_period

        if average_daily <= 0:
            return None

        return int(current_volume / average_daily)
