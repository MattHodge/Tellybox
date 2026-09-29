"""PR-2 / PR-4 / A-13: watchers, per-profile viewing sessions and exhaustion."""

import json
from datetime import timedelta

import pytest

from tellybox.timer import Action, Activity, TimeUpReason

from timer_helpers import AMS, MIN, START, policy

PLAYING, PAUSED, STOPPED = Activity.PLAYING, Activity.PAUSED, Activity.STOPPED


def two(make_timer, **kwargs):
    return make_timer(policy(1, **kwargs), policy(2, **kwargs))


def test_only_watchers_accrue_time(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    timer.tick(clock.now())
    assert timer.watchers == {1}
    assert timer.usage(1).used_s == 10 * MIN
    assert timer.usage(2).used_s == 0


def test_no_pick_means_every_profile_watches(make_timer, clock):
    timer = two(make_timer)
    assert timer.watchers == {1, 2}
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=5)
    timer.tick(clock.now())
    assert timer.usage(1).used_s == timer.usage(2).used_s == 5 * MIN


def test_pick_with_none_means_everyone(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    timer.on_pick(clock.now())
    assert timer.watchers == {1, 2}


def test_remaining_comes_from_the_watchers_only(make_timer, clock):
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=20))
    assert timer.on_pick(clock.now(), [1]).remaining_s == 60 * MIN
    assert timer.on_pick(clock.now(), [1, 2]).remaining_s == 20 * MIN


def test_group_needs_every_member_to_have_time(make_timer, clock):
    """PR-4."""
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=10))
    timer.on_pick(clock.now(), [2])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=11)
    timer.tick(clock.now())
    timer.set_activity(clock.now(), STOPPED)
    group = timer.group_decision(clock.now(), [1, 2])
    assert not group.can_start and group.reason is TimeUpReason.ALLOWANCE
    assert timer.group_decision(clock.now(), [1]).can_start
    refused = timer.on_pick(clock.now(), [1, 2])
    assert not refused.can_start and timer.watchers == {2}  # a refused pick changes nothing
    assert timer.on_pick(clock.now(), [1]).can_start and timer.watchers == {1}


def test_group_decision_has_no_side_effects(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    before = timer.snapshot()
    timer.group_decision(clock.now(), [2])
    assert timer.snapshot() == before and timer.watchers == {1}


def test_group_needs_a_non_empty_list_of_known_profiles(make_timer, clock):
    timer = two(make_timer)
    with pytest.raises(ValueError):
        timer.group_decision(clock.now(), [])
    with pytest.raises(KeyError):
        timer.on_pick(clock.now(), [1, 99])


def test_session_max_is_per_profile(make_timer, clock):
    """A watched 90 minutes; B can still start (A-13)."""
    timer = two(make_timer, allowance_min=300, max_session_min=90)
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=91)
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.SESSION_MAX
    assert decision.action is Action.FINISH_THEN_STOP
    timer.set_activity(clock.now(), STOPPED)
    assert not timer.group_decision(clock.now(), [1]).can_start
    assert not timer.group_decision(clock.now(), [1, 2]).can_start
    picked = timer.on_pick(clock.now(), [2])
    assert picked.can_start and picked.reason is None
    assert picked.session_started_at == clock.now()  # B's own session starts now
    assert timer.profile_status(clock.now(), 1).reason is TimeUpReason.SESSION_MAX
    assert timer.profile_status(clock.now(), 2).can_start


def test_a_joining_a_running_group_counts_from_the_join(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [2])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=30)
    decision = timer.on_pick(clock.now(), [1, 2])
    assert decision.session_started_at == START  # earliest session among the watchers
    clock.advance(minutes=10)
    timer.tick(clock.now())
    assert timer.usage(1).used_s == 10 * MIN
    assert timer.usage(2).used_s == 40 * MIN
    assert timer.profile_status(clock.now(), 1).session_elapsed_s == 10 * MIN
    assert timer.profile_status(clock.now(), 2).session_elapsed_s == 40 * MIN


def test_replaced_profile_starts_its_break_at_that_moment(make_timer, clock):
    """WT-3 per profile: A's 15 minute break starts when B's pick replaces it."""
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=20)
    timer.on_pick(clock.now(), [2])  # A stops watching, B starts, playback continues
    clock.advance(minutes=14)
    timer.tick(clock.now())
    assert timer.profile_status(clock.now(), 1).session_elapsed_s == 34 * MIN  # break not over
    assert timer.profile_status(clock.now(), 2).session_elapsed_s == 14 * MIN
    clock.advance(minutes=1)
    timer.tick(clock.now())
    assert timer.profile_status(clock.now(), 1).session_elapsed_s is None  # A's session ended
    assert timer.profile_status(clock.now(), 2).session_elapsed_s == 15 * MIN


def test_returning_within_the_break_extends_the_session(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=20)
    timer.on_pick(clock.now(), [2])
    clock.advance(minutes=10)
    timer.on_pick(clock.now(), [1])
    assert timer.profile_status(clock.now(), 1).session_elapsed_s == 30 * MIN


def test_session_break_ends_a_watchers_session_only_when_not_playing(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    timer.set_activity(clock.now(), PAUSED)
    clock.advance(minutes=15)
    assert timer.tick(clock.now()).session_started_at is None


def test_max_session_takes_the_watchers_events_exactly(make_timer, clock):
    timer = make_timer(policy(1, 300, max_session_min=60), policy(2, 300, max_session_min=30))
    timer.on_pick(clock.now(), [1, 2])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=50)
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.SESSION_MAX
    assert decision.grace_deadline == START + timedelta(minutes=45)  # B's limit, anchored when hit


def test_blocking_a_non_watcher_leaves_playback_alone(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    decision = timer.set_blocked(clock.now(), 2, True)
    assert decision.action is Action.CONTINUE and decision.can_start
    status = timer.profile_status(clock.now(), 2)
    assert not status.can_start and status.reason is TimeUpReason.BLOCKED and not status.watching
    assert not timer.group_decision(clock.now(), [1, 2]).can_start


def test_blocking_a_watcher_stops_now(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1, 2])
    timer.set_activity(clock.now(), PLAYING)
    decision = timer.set_blocked(clock.now(), 2, True)
    assert decision.action is Action.STOP_NOW and decision.reason is TimeUpReason.BLOCKED


def test_grace_belongs_to_the_watchers(make_timer, clock):
    """WT-4/5: B running out while replaced by A does not stop A's playback."""
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=10))
    timer.on_pick(clock.now(), [2])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=5)
    timer.on_pick(clock.now(), [1])
    clock.advance(minutes=20)
    decision = timer.tick(clock.now())
    assert decision.action is Action.CONTINUE and decision.remaining_s == 40 * MIN
    assert timer.usage(2).used_s == 5 * MIN


def test_grace_for_a_group_is_anchored_at_the_first_member_to_run_out(make_timer, clock):
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=10))
    timer.on_pick(clock.now(), [1, 2])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=12)
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.ALLOWANCE
    assert decision.grace_deadline == START + timedelta(minutes=25)
    clock.advance(minutes=14)
    assert timer.tick(clock.now()).action is Action.STOP_NOW
    timer.set_activity(clock.now(), STOPPED)
    assert timer.on_pick(clock.now(), [1]).can_start  # A alone can still start


def test_profile_status(make_timer, clock):
    timer = make_timer(policy(1, allowance_min=60), policy(2, allowance_min=20))
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    one, two_ = timer.profile_status(clock.now(), 1), timer.profile_status(clock.now(), 2)
    assert (one.remaining_s, one.can_start, one.reason, one.watching) == (50 * MIN, True, None, True)
    assert (two_.remaining_s, two_.watching, two_.session_elapsed_s) == (20 * MIN, False, None)
    timer.set_unlimited(clock.now(), 2, True)
    assert timer.profile_status(clock.now(), 2).remaining_s is None
    with pytest.raises(KeyError):
        timer.profile_status(clock.now(), 99)


def test_set_watchers_reattaches_without_a_check(make_timer, clock):
    timer = two(make_timer)
    timer.set_blocked(clock.now(), 2, True)
    decision = timer.set_watchers(clock.now(), [2])
    assert timer.watchers == {2} and decision.reason is TimeUpReason.BLOCKED
    timer.set_watchers(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=3)
    timer.tick(clock.now())
    assert timer.usage(1).used_s == 3 * MIN and timer.usage(2).used_s == 0


def test_deleted_profiles_leave_the_watchers(make_timer, clock, settings):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1, 2])
    timer.set_policies(settings, [policy(1)], clock.now())
    assert timer.watchers == {1}
    timer.set_policies(settings, [policy(2)], clock.now())  # all watchers gone: back to everyone
    assert timer.watchers == {2}


# -- snapshot v2 -----------------------------------------------------------


def restart(make_timer, timer, **kwargs):
    snapshot = json.loads(json.dumps(timer.snapshot()))
    return make_timer(policy(1), policy(2), usages=[timer.usage(1), timer.usage(2)], snapshot=snapshot, **kwargs)


def test_snapshot_v2_restores_watchers_sessions_and_exhaustion(make_timer, clock):
    timer = make_timer(policy(1, allowance_min=30), policy(2))
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=32)
    timer.tick(clock.now())
    assert timer.snapshot()["version"] == 2
    clock.advance(minutes=1)
    restored = make_timer(
        policy(1, allowance_min=30),
        policy(2),
        usages=[timer.usage(1), timer.usage(2)],
        snapshot=json.loads(json.dumps(timer.snapshot())),
    )
    decision = restored.tick(clock.now())
    assert restored.watchers == {1}
    assert decision.reason is TimeUpReason.ALLOWANCE
    assert decision.grace_deadline == START + timedelta(minutes=45)
    assert decision.session_started_at == START
    assert restored.profile_status(clock.now(), 2).session_elapsed_s is None


def test_snapshot_v2_keeps_a_replaced_profiles_break(make_timer, clock):
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    timer.on_pick(clock.now(), [2])
    clock.advance(minutes=10)
    timer.tick(clock.now())
    clock.advance(minutes=1)
    restored = restart(make_timer, timer)
    assert restored.profile_status(clock.now(), 1).session_elapsed_s == 21 * MIN
    clock.advance(minutes=5)  # A's break began at minute 10: over at minute 25
    restored.tick(clock.now())
    assert restored.profile_status(clock.now(), 1).session_elapsed_s is None


def test_snapshot_without_a_pick_restores_as_everyone(make_timer, clock):
    timer = two(make_timer)
    assert restart(make_timer, timer).watchers == {1, 2}


V1_SNAPSHOT = {
    "version": 1,
    "as_of": START.isoformat(),
    "day": "2026-09-28",
    "activity": "playing",
    "session_started_at": (START - timedelta(minutes=30)).isoformat(),
    "last_active_at": START.isoformat(),
    "exhausted": {},
}


def test_v1_snapshot_restores_with_every_profile_watching(make_timer, clock):
    timer = make_timer(policy(1), policy(2), snapshot=V1_SNAPSHOT)
    assert timer.watchers == {1, 2}
    decision = timer.tick(clock.now())
    assert decision.session_started_at == START - timedelta(minutes=30)
    assert timer.profile_status(clock.now(), 1).session_elapsed_s == 30 * MIN
    assert timer.profile_status(clock.now(), 2).session_elapsed_s == 30 * MIN


def test_v1_snapshot_exhaustion_applies_to_every_profile(make_timer, clock):
    snap = dict(
        V1_SNAPSHOT,
        exhausted={"session_max": {"at": START.isoformat(), "grace_deadline": (START + timedelta(minutes=15)).isoformat()}},
    )
    timer = make_timer(policy(1, max_session_min=20), policy(2, max_session_min=20), snapshot=snap)
    assert timer.tick(clock.now()).reason is TimeUpReason.SESSION_MAX
    assert not timer.group_decision(clock.now(), [2]).can_start


# -- rollover --------------------------------------------------------------


def test_rollover_across_a_group_resets_usage_and_exhaustion_for_all(make_timer, clock):
    """WT-1 across a group: 03:30 local, both watching, allowance 30."""
    clock.set(START.replace(day=29, hour=1, minute=40))  # 03:40 local
    timer = make_timer(policy(1, allowance_min=30), policy(2, allowance_min=30, max_session_min=300))
    timer.on_pick(clock.now(), [1, 2])
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=25)  # both at 25 minutes at 04:05 local: rolled over at 04:00
    decision = timer.tick(clock.now())
    assert clock.now().astimezone(AMS).hour == 4
    assert timer.usage(1).used_s == timer.usage(2).used_s == 5 * MIN  # only time since the reset
    assert decision.reason is None and decision.remaining_s == 25 * MIN
    assert timer.watchers == {1, 2}  # still playing: the group stays
    prev = {u.day.isoformat(): u.used_s for u in timer.pop_dirty_usage() if u.profile_id == 1}
    assert prev["2026-09-28"] == 20 * MIN


def test_rollover_while_stopped_forgets_yesterdays_group(make_timer, clock):
    clock.set(START.replace(day=29, hour=1, minute=40))
    timer = two(make_timer)
    timer.on_pick(clock.now(), [1])
    assert timer.watchers == {1}
    clock.advance(minutes=30)
    timer.tick(clock.now())
    assert timer.watchers == {1, 2}
