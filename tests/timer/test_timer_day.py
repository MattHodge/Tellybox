"""WT-1: a day runs from the reset time (local wall time) to the next one."""

from datetime import UTC, date, datetime, time

from tellybox.timer import day_for, next_reset_after

from timer_helpers import AMS

FOUR = time(4, 0)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_time_before_reset_belongs_to_previous_day():
    assert day_for(utc(2026, 9, 28, 1, 59, 59), FOUR, AMS) == date(2026, 9, 27)  # 03:59:59 CEST


def test_day_starts_exactly_at_reset():
    assert day_for(utc(2026, 9, 28, 2, 0), FOUR, AMS) == date(2026, 9, 28)  # 04:00 CEST


def test_next_reset_is_next_local_0400():
    assert next_reset_after(utc(2026, 9, 28, 12, 0), FOUR, AMS) == utc(2026, 9, 29, 2, 0)


def test_next_reset_at_reset_instant_is_the_following_day():
    assert next_reset_after(utc(2026, 9, 28, 2, 0), FOUR, AMS) == utc(2026, 9, 29, 2, 0)


def test_next_reset_is_utc():
    assert next_reset_after(utc(2026, 9, 28, 12, 0), FOUR, AMS).utcoffset().total_seconds() == 0


def test_spring_forward_day_is_23_hours():
    # 2026-03-29 02:00 CET -> 03:00 CEST. Day of 28 March: 03:00 UTC -> 02:00 UTC next day.
    assert next_reset_after(utc(2026, 3, 28, 3, 0), FOUR, AMS) == utc(2026, 3, 29, 2, 0)
    assert day_for(utc(2026, 3, 29, 1, 59), FOUR, AMS) == date(2026, 3, 28)
    assert day_for(utc(2026, 3, 29, 2, 0), FOUR, AMS) == date(2026, 3, 29)


def test_fall_back_day_is_25_hours():
    # 2026-10-25 03:00 CEST -> 02:00 CET. Day of 24 October: 02:00 UTC -> 03:00 UTC next day.
    assert next_reset_after(utc(2026, 10, 24, 2, 0), FOUR, AMS) == utc(2026, 10, 25, 3, 0)
    assert day_for(utc(2026, 10, 25, 2, 30), FOUR, AMS) == date(2026, 10, 24)  # 03:30 CET
    assert day_for(utc(2026, 10, 25, 3, 0), FOUR, AMS) == date(2026, 10, 25)


def test_ambiguous_reset_time_uses_first_occurrence_and_does_not_flip_back():
    reset = time(2, 30)  # happens twice on 2026-10-25
    assert day_for(utc(2026, 10, 25, 0, 29), reset, AMS) == date(2026, 10, 24)
    assert day_for(utc(2026, 10, 25, 0, 30), reset, AMS) == date(2026, 10, 25)  # 02:30 CEST
    assert day_for(utc(2026, 10, 25, 1, 15), reset, AMS) == date(2026, 10, 25)  # 02:15 CET


def test_nonexistent_reset_time_resolves_one_hour_later():
    reset = time(2, 30)  # does not exist on 2026-03-29; resolves to 03:30 CEST
    assert next_reset_after(utc(2026, 3, 28, 12, 0), reset, AMS) == utc(2026, 3, 29, 1, 30)
    assert day_for(utc(2026, 3, 29, 1, 15), reset, AMS) == date(2026, 3, 28)
    assert day_for(utc(2026, 3, 29, 1, 30), reset, AMS) == date(2026, 3, 29)
