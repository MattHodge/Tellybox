"""WT-1: the watch day runs from the reset time (local wall time) to the next.

The reset instant of a date is its reset wall time resolved with ``fold=0``:
an ambiguous time (DST fall-back) resets at its first occurrence, and a
non-existent time (DST spring-forward gap) resets one hour later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def _reset_instant(day: date, reset: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, reset, tzinfo=tz).astimezone(UTC)


def day_for(now: datetime, reset: time, tz: ZoneInfo) -> date:
    """The watch day ``now`` belongs to."""
    local_date = now.astimezone(tz).date()
    if now >= _reset_instant(local_date, reset, tz):
        return local_date
    return local_date - timedelta(days=1)


def next_reset_after(now: datetime, reset: time, tz: ZoneInfo) -> datetime:
    """The first reset strictly after ``now``, as aware UTC."""
    return _reset_instant(day_for(now, reset, tz) + timedelta(days=1), reset, tz)
