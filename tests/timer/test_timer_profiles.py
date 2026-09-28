"""PR-4 / A-1: several profiles watching together."""

from datetime import timedelta

from tellybox.timer import Action, Activity, CountingMode, DayUsage, TimeUpReason

from timer_helpers import MIN, START, policy

PLAYING, PAUSED = Activity.PLAYING, Activity.PAUSED


def test_time_accrues_to_every_profile_and_remaining_is_the_minimum(make_timer, clock):
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=40))
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    decision = timer.tick(clock.now())
    assert timer.usage(1).used_s == timer.usage(2).used_s == 10 * MIN
    assert decision.remaining_s == 30 * MIN
    assert timer.pop_counted_s() == 10 * MIN  # not multiplied by profile count


def test_one_profile_out_of_time_exhausts_the_group(make_timer, clock):
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=20))
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=25)
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.ALLOWANCE and not decision.can_start
    assert decision.grace_deadline == START + timedelta(minutes=35)


def test_one_blocked_profile_blocks_the_group(make_timer, clock):
    timer = make_timer(policy(1), policy(2))
    decision = timer.set_blocked(clock.now(), 2, True)
    assert decision.action is Action.STOP_NOW and decision.reason is TimeUpReason.BLOCKED


def test_unlimited_profile_is_ignored_for_remaining(make_timer, clock):
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=20))
    assert timer.set_unlimited(clock.now(), 2, True).remaining_s == 60 * MIN
    assert timer.set_unlimited(clock.now(), 1, True).remaining_s is None


def test_session_max_lifted_only_when_every_profile_is_unlimited(make_timer, clock):
    timer = make_timer(policy(1, 300, max_session_min=60), policy(2, 300, max_session_min=60))
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=65)
    assert timer.set_unlimited(clock.now(), 1, True).reason is TimeUpReason.SESSION_MAX
    assert timer.set_unlimited(clock.now(), 2, True).reason is None


def test_counting_mode_is_per_profile(make_timer, clock):
    timer = make_timer(policy(1, mode=CountingMode.IGNORE_PAUSES), policy(2, mode=CountingMode.WALL_CLOCK))
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=5)
    timer.set_activity(clock.now(), PAUSED)
    clock.advance(minutes=5)
    timer.tick(clock.now())
    assert (timer.usage(1).used_s, timer.usage(2).used_s) == (5 * MIN, 10 * MIN)


def test_missing_usage_rows_start_at_zero(make_timer, clock):
    timer = make_timer(policy(1), policy(2), usages=[DayUsage(1, START.date(), used_s=120)])
    assert (timer.usage(1).used_s, timer.usage(2).used_s) == (120, 0)
