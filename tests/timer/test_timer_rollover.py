"""WT-1: the daily reset while playing, and what it clears."""

from datetime import UTC, date, datetime

from tellybox.timer import Action, Activity, DayUsage, TimeUpReason

from timer_helpers import MIN

PLAYING = Activity.PLAYING
BEFORE_RESET = datetime(2026, 9, 28, 1, 50, tzinfo=UTC)  # 03:50 local
RESET = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)  # 04:00 local


def test_playing_across_reset_splits_seconds_between_days(make_timer, clock):
    clock.set(BEFORE_RESET)
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=20)  # single tick at 04:10
    timer.tick(clock.now())
    old, new = timer.pop_dirty_usage()
    assert (old.day, old.used_s) == (date(2026, 9, 27), 10 * MIN)
    assert (new.day, new.used_s) == (date(2026, 9, 28), 10 * MIN)
    assert timer.usage(1).day == date(2026, 9, 28)


def test_rollover_clears_allowance_exhaustion_and_overrides(make_timer, clock):
    clock.set(datetime(2026, 9, 28, 1, 0, tzinfo=UTC))  # 03:00 local
    timer = make_timer(allowance_min=30, max_session_min=300)
    timer.set_activity(clock.now(), PLAYING)
    timer.add_extra(clock.now(), 1, 5 * MIN)
    clock.set(datetime(2026, 9, 28, 1, 55, tzinfo=UTC))
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.ALLOWANCE and decision.action is Action.STOP_NOW
    clock.set(RESET)
    decision = timer.tick(clock.now())
    assert decision.action is Action.CONTINUE and decision.can_start
    assert decision.remaining_s == 30 * MIN
    assert timer.usage(1).extra_s == 0


def test_rollover_clears_block(make_timer, clock):
    clock.set(BEFORE_RESET)
    timer = make_timer()
    assert timer.set_blocked(clock.now(), 1, True).reason is TimeUpReason.BLOCKED
    clock.set(RESET)
    decision = timer.tick(clock.now())
    assert decision.reason is None and decision.can_start


def test_viewing_session_continues_across_reset(make_timer, clock):
    clock.set(BEFORE_RESET)
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=30)
    assert timer.tick(clock.now()).session_started_at == BEFORE_RESET


def test_usages_for_other_days_are_ignored(make_timer, clock):
    timer = make_timer(usages=[DayUsage(1, date(2026, 9, 27), used_s=999)])
    assert timer.usage(1).used_s == 0 and timer.usage(1).day == date(2026, 9, 28)
