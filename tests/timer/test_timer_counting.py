"""WT-2 counting modes, WT-6 rewatching, and group counted seconds."""

import pytest

from tellybox.timer import Activity, CountingMode

from timer_helpers import MIN

PLAYING, PAUSED, STOPPED = Activity.PLAYING, Activity.PAUSED, Activity.STOPPED


def run(timer, clock, steps):
    """steps: (activity, minutes) pairs; each activity is held for the minutes given."""
    for activity, minutes in steps:
        timer.set_activity(clock.now(), activity)
        clock.advance(minutes=minutes)
    return timer.tick(clock.now())


def test_ignore_pauses_counts_only_playing_time(make_timer, clock):
    timer = make_timer(mode=CountingMode.IGNORE_PAUSES)
    run(timer, clock, [(PLAYING, 10), (PAUSED, 5), (PLAYING, 3), (STOPPED, 20)])
    assert timer.usage(1).used_s == 13 * MIN


def test_wall_clock_counts_playing_and_paused_but_not_stopped(make_timer, clock):
    timer = make_timer(mode=CountingMode.WALL_CLOCK)
    run(timer, clock, [(PLAYING, 10), (PAUSED, 5), (PLAYING, 3), (STOPPED, 20)])
    assert timer.usage(1).used_s == 18 * MIN


def test_remaining_reflects_usage(make_timer, clock):
    timer = make_timer(allowance_min=60)
    decision = run(timer, clock, [(PLAYING, 25)])
    assert decision.remaining_s == 35 * MIN


def test_accrual_is_independent_of_tick_spacing(make_timer, clock):
    sparse, dense = make_timer(), make_timer()
    sparse.set_activity(clock.now(), PLAYING)
    dense.set_activity(clock.now(), PLAYING)
    for _ in range(100):
        clock.advance(seconds=7.3)
        dense.tick(clock.now())
    sparse.tick(clock.now())
    assert sparse.usage(1).used_s == 730
    assert dense.usage(1).used_s == pytest.approx(730)


def test_set_activity_accrues_under_the_old_activity(make_timer, clock):
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=4)
    timer.set_activity(clock.now(), PAUSED)  # the 4 minutes were playing
    assert timer.usage(1).used_s == 4 * MIN
    assert timer.activity is PAUSED


def test_rewatching_counts_like_any_viewing(make_timer, clock):
    """WT-6."""
    timer = make_timer()
    for _ in range(2):  # the same episode twice
        timer.on_pick(clock.now())
        run(timer, clock, [(PLAYING, 12), (STOPPED, 1)])
    assert timer.usage(1).used_s == 24 * MIN


def test_pop_counted_s_returns_group_seconds_since_last_pop(make_timer, clock):
    timer = make_timer(mode=CountingMode.WALL_CLOCK)
    run(timer, clock, [(PLAYING, 5), (PAUSED, 2)])
    assert timer.pop_counted_s() == 7 * MIN
    assert timer.pop_counted_s() == 0
    run(timer, clock, [(PLAYING, 1)])
    assert timer.pop_counted_s() == 1 * MIN


def test_pop_counted_s_excludes_pauses_in_ignore_pauses_mode(make_timer, clock):
    timer = make_timer()
    run(timer, clock, [(PLAYING, 5), (PAUSED, 2)])
    assert timer.pop_counted_s() == 5 * MIN


def test_pop_dirty_usage_returns_changed_rows_once(make_timer, clock):
    timer = make_timer()
    assert timer.pop_dirty_usage() == []
    run(timer, clock, [(PLAYING, 1)])
    [row] = timer.pop_dirty_usage()
    assert (row.profile_id, row.used_s) == (1, 60)
    assert timer.pop_dirty_usage() == []


def test_usage_returns_a_copy(make_timer):
    timer = make_timer()
    timer.usage(1).used_s = 999
    assert timer.usage(1).used_s == 0
