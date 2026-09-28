"""WT-4/WT-5 time up and grace, WT-7 parent overrides."""

from datetime import timedelta

import pytest

from tellybox.timer import Action, Activity, CountingMode, DayUsage, TimeUpReason

from timer_helpers import MIN, START, policy

PLAYING, PAUSED, STOPPED = Activity.PLAYING, Activity.PAUSED, Activity.STOPPED
TODAY = START.date()  # 14:00 local on 28 Sept belongs to day 28 Sept


def playing(make_timer, clock, **kwargs):
    timer = make_timer(**kwargs)
    timer.on_pick(clock.now())
    timer.set_activity(clock.now(), PLAYING)
    return timer


def test_time_left_means_continue(make_timer, clock):
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=29)
    decision = timer.tick(clock.now())
    assert decision.action is Action.CONTINUE and decision.reason is None
    assert decision.can_start and decision.autoplay_allowed


def test_allowance_runs_out_mid_episode_finish_then_stop(make_timer, clock):
    """WT-4."""
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=31)
    decision = timer.tick(clock.now())
    assert decision.action is Action.FINISH_THEN_STOP
    assert decision.reason is TimeUpReason.ALLOWANCE
    assert decision.grace_deadline == START + timedelta(minutes=30 + 15)
    assert decision.remaining_s == 0
    assert not decision.can_start and not decision.autoplay_allowed


def test_grace_is_capped_and_deadline_is_exact_with_sparse_ticks(make_timer, clock):
    """WT-5: no ticks for two hours still yields the exact deadline."""
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(hours=2)
    decision = timer.tick(clock.now())
    assert decision.action is Action.STOP_NOW
    assert decision.grace_deadline == START + timedelta(minutes=45)


def test_stop_now_exactly_at_grace_deadline(make_timer, clock):
    timer = playing(make_timer, clock, allowance_min=30)
    clock.set(START + timedelta(minutes=45) - timedelta(microseconds=1))
    assert timer.tick(clock.now()).action is Action.FINISH_THEN_STOP
    clock.set(START + timedelta(minutes=45))
    assert timer.tick(clock.now()).action is Action.STOP_NOW


def test_grace_seconds_still_count(make_timer, clock):
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=40)
    timer.tick(clock.now())
    assert timer.usage(1).used_s == 40 * MIN


def test_allowance_runs_out_while_paused_in_wall_clock_gets_grace(make_timer, clock):
    timer = playing(make_timer, clock, allowance_min=30, mode=CountingMode.WALL_CLOCK)
    clock.advance(minutes=20)
    timer.set_activity(clock.now(), PAUSED)
    clock.advance(minutes=12)
    decision = timer.tick(clock.now())
    assert decision.action is Action.FINISH_THEN_STOP
    assert decision.grace_deadline == START + timedelta(minutes=45)


def test_exhausted_while_stopped_has_no_grace(make_timer, clock):
    timer = make_timer(allowance_min=30, usages=[DayUsage(1, TODAY, used_s=30 * MIN)])
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.ALLOWANCE
    assert decision.grace_deadline is None
    assert not decision.can_start


def test_refused_pick_does_not_start_a_session(make_timer, clock):
    timer = make_timer(allowance_min=30, usages=[DayUsage(1, TODAY, used_s=30 * MIN)])
    decision = timer.on_pick(clock.now())
    assert not decision.can_start and decision.session_started_at is None


def test_pick_during_grace_is_refused(make_timer, clock):
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=32)
    assert not timer.on_pick(clock.now()).can_start


def test_blocked_stops_now_without_grace(make_timer, clock):
    """WT-7."""
    timer = playing(make_timer, clock)
    clock.advance(minutes=5)
    decision = timer.set_blocked(clock.now(), 1, True)
    assert decision.action is Action.STOP_NOW
    assert decision.reason is TimeUpReason.BLOCKED
    assert decision.grace_deadline is None
    assert not decision.can_start and not decision.autoplay_allowed
    decision = timer.set_blocked(clock.now(), 1, False)
    assert decision.action is Action.CONTINUE and decision.can_start


def test_blocked_overrides_grace(make_timer, clock):
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=31)
    assert timer.set_blocked(clock.now(), 1, True).action is Action.STOP_NOW


def test_extra_minutes_during_grace_clear_allowance_exhaustion(make_timer, clock):
    """WT-7."""
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=35)
    decision = timer.add_extra(clock.now(), 1, 10 * MIN)
    assert decision.action is Action.CONTINUE and decision.reason is None
    assert decision.autoplay_allowed and decision.can_start
    assert decision.remaining_s == 5 * MIN
    clock.advance(minutes=6)
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.ALLOWANCE
    assert decision.grace_deadline == START + timedelta(minutes=40 + 15)


def test_extra_minutes_are_cumulative(make_timer, clock):
    timer = make_timer(allowance_min=30)
    timer.add_extra(clock.now(), 1, 5 * MIN)
    decision = timer.add_extra(clock.now(), 1, 5 * MIN)
    assert timer.usage(1).extra_s == 10 * MIN
    assert decision.remaining_s == 40 * MIN


def test_unlimited_clears_allowance_exhaustion(make_timer, clock):
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=31)
    decision = timer.set_unlimited(clock.now(), 1, True)
    assert decision.action is Action.CONTINUE and decision.remaining_s is None
    clock.advance(hours=3)
    decision = timer.tick(clock.now())
    assert decision.action is Action.CONTINUE and decision.remaining_s is None


def test_overrides_mark_usage_dirty(make_timer, clock):
    timer = make_timer()
    timer.set_blocked(clock.now(), 1, True)
    [row] = timer.pop_dirty_usage()
    assert row.blocked


def test_override_for_unknown_profile_raises(make_timer, clock):
    timer = make_timer()
    with pytest.raises(KeyError):
        timer.add_extra(clock.now(), 99, 60)


def test_set_policies_applies_new_allowance_immediately(make_timer, clock, settings):
    timer = playing(make_timer, clock, allowance_min=30)
    clock.advance(minutes=31)
    assert timer.tick(clock.now()).reason is TimeUpReason.ALLOWANCE
    timer.set_policies(settings, [policy(1, allowance_min=60)], clock.now())
    decision = timer.tick(clock.now())
    assert decision.action is Action.CONTINUE and decision.remaining_s == 29 * MIN


def test_set_policies_adds_profiles_with_zero_usage(make_timer, clock, settings):
    timer = playing(make_timer, clock)
    clock.advance(minutes=5)
    timer.set_policies(settings, [policy(1), policy(2)], clock.now())
    clock.advance(minutes=5)
    timer.tick(clock.now())
    assert (timer.usage(1).used_s, timer.usage(2).used_s) == (10 * MIN, 5 * MIN)
