"""WT-8: timer state survives restarts via snapshot/restore."""

import json
from datetime import timedelta

from tellybox.timer import Action, Activity, TimeUpReason

from timer_helpers import MIN, START

PLAYING, PAUSED = Activity.PLAYING, Activity.PAUSED


def restart(make_timer, timer, **kwargs):
    """Round-trip through JSON and persisted usage, as a real restart would."""
    snapshot = json.loads(json.dumps(timer.snapshot()))
    return make_timer(usages=[timer.usage(1)], snapshot=snapshot, **kwargs)


def test_snapshot_is_json_serialisable(make_timer, clock):
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    json.dumps(timer.snapshot())


def test_restore_keeps_viewing_session_and_exhaustion(make_timer, clock):
    timer = make_timer(allowance_min=30)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=32)
    timer.tick(clock.now())
    clock.advance(minutes=1)
    restored = restart(make_timer, timer, allowance_min=30)
    decision = restored.tick(clock.now())
    assert decision.session_started_at == START
    assert decision.reason is TimeUpReason.ALLOWANCE
    assert decision.grace_deadline == START + timedelta(minutes=45)
    assert decision.action is Action.FINISH_THEN_STOP


def test_restore_does_not_count_downtime_and_starts_stopped(make_timer, clock):
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    timer.tick(clock.now())
    clock.advance(minutes=5)  # server down
    restored = restart(make_timer, timer)
    clock.advance(minutes=5)
    restored.tick(clock.now())
    assert restored.activity is Activity.STOPPED
    assert restored.usage(1).used_s == 10 * MIN


def test_restore_after_break_ends_the_session(make_timer, clock):
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    timer.set_activity(clock.now(), PAUSED)
    snapshot = json.loads(json.dumps(timer.snapshot()))
    clock.advance(minutes=15)
    restored = make_timer(snapshot=snapshot)
    assert restored.tick(clock.now()).session_started_at is None


def test_restore_within_break_keeps_the_session(make_timer, clock):
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    timer.tick(clock.now())  # snapshot() reflects the last call
    snapshot = json.loads(json.dumps(timer.snapshot()))  # taken while playing
    clock.advance(minutes=14)
    restored = make_timer(snapshot=snapshot)
    assert restored.tick(clock.now()).session_started_at == START
    clock.advance(minutes=1)  # break counts from the snapshot time
    assert restored.tick(clock.now()).session_started_at is None


def test_restore_on_a_new_day_clears_allowance_exhaustion(make_timer, clock):
    timer = make_timer(allowance_min=30)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=31)
    snapshot = json.loads(json.dumps(timer.snapshot()))
    clock.advance(days=1)
    restored = make_timer(allowance_min=30, snapshot=snapshot)
    decision = restored.tick(clock.now())
    assert decision.reason is None and decision.can_start
