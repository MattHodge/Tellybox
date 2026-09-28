"""WT-3: viewing sessions, the session break and the maximum session length."""

from datetime import timedelta

from tellybox.timer import Action, Activity, CountingMode, TimeUpReason

from timer_helpers import MIN, START

PLAYING, PAUSED, STOPPED = Activity.PLAYING, Activity.PAUSED, Activity.STOPPED


def test_first_playing_starts_a_viewing_session(make_timer, clock):
    timer = make_timer()
    assert timer.tick(clock.now()).session_started_at is None
    clock.advance(minutes=1)
    decision = timer.set_activity(clock.now(), PLAYING)
    assert decision.session_started_at == START + timedelta(minutes=1)
    clock.advance(minutes=10)
    assert timer.tick(clock.now()).session_elapsed_s == 10 * MIN


def test_pick_starts_a_viewing_session(make_timer, clock):
    timer = make_timer()
    decision = timer.on_pick(clock.now())
    assert decision.can_start and decision.session_started_at == START


def test_pause_shorter_than_break_keeps_the_session(make_timer, clock):
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=5)
    timer.set_activity(clock.now(), PAUSED)
    clock.advance(minutes=14, seconds=59)
    decision = timer.set_activity(clock.now(), PLAYING)
    assert decision.session_started_at == START


def test_pause_of_full_break_ends_the_session(make_timer, clock):
    timer = make_timer()
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=5)
    timer.set_activity(clock.now(), PAUSED)
    clock.advance(minutes=15)
    assert timer.tick(clock.now()).session_started_at is None
    decision = timer.set_activity(clock.now(), PLAYING)
    assert decision.session_started_at == clock.now()


def test_later_pick_extends_the_break(make_timer, clock):
    timer = make_timer()
    timer.on_pick(clock.now())
    clock.advance(minutes=10)
    timer.on_pick(clock.now())
    clock.advance(minutes=10)
    assert timer.tick(clock.now()).session_started_at == START


def test_stop_and_restart_within_break_accumulates_toward_max(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=60)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=40)
    timer.set_activity(clock.now(), STOPPED)
    clock.advance(minutes=10)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=10)
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.SESSION_MAX
    assert decision.action is Action.FINISH_THEN_STOP
    assert decision.grace_deadline == START + timedelta(minutes=60 + 15)


def test_max_session_grace_then_stop_now_at_exact_deadline(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=60)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=70)  # one sparse tick, 10 minutes into grace
    decision = timer.tick(clock.now())
    assert decision.action is Action.FINISH_THEN_STOP
    assert not decision.can_start and not decision.autoplay_allowed
    deadline = START + timedelta(minutes=75)
    assert decision.grace_deadline == deadline
    clock.set(deadline - timedelta(seconds=1))
    assert timer.tick(clock.now()).action is Action.FINISH_THEN_STOP
    clock.set(deadline)
    assert timer.tick(clock.now()).action is Action.STOP_NOW


def test_max_session_applies_while_paused(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=60)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=50)
    timer.set_activity(clock.now(), PAUSED)
    clock.advance(minutes=12)  # paused < break, session still running
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.SESSION_MAX
    assert decision.grace_deadline == START + timedelta(minutes=75)


def test_max_session_not_applied_in_wall_clock_mode(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=30, mode=CountingMode.WALL_CLOCK)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=60)
    decision = timer.tick(clock.now())
    assert decision.action is Action.CONTINUE and decision.can_start


def test_max_session_reached_while_stopped_has_no_grace(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=60)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=50)
    timer.set_activity(clock.now(), STOPPED)
    clock.advance(minutes=12)
    decision = timer.tick(clock.now())
    assert decision.reason is TimeUpReason.SESSION_MAX
    assert decision.grace_deadline is None
    assert not decision.can_start
    assert not timer.on_pick(clock.now()).can_start


def test_session_max_clears_when_the_session_ends(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=60)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=75)
    assert timer.tick(clock.now()).action is Action.STOP_NOW
    timer.set_activity(clock.now(), STOPPED)
    clock.advance(minutes=14)
    assert not timer.tick(clock.now()).can_start
    clock.advance(minutes=1)
    decision = timer.tick(clock.now())
    assert decision.can_start and decision.reason is None and decision.action is Action.CONTINUE
    assert timer.on_pick(clock.now()).session_started_at == clock.now()


def test_extra_minutes_do_not_lift_session_max(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=60)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=65)
    decision = timer.add_extra(clock.now(), 1, 30 * MIN)
    assert decision.reason is TimeUpReason.SESSION_MAX and not decision.can_start


def test_unlimited_lifts_session_max(make_timer, clock):
    timer = make_timer(allowance_min=300, max_session_min=60)
    timer.set_activity(clock.now(), PLAYING)
    clock.advance(minutes=65)
    decision = timer.set_unlimited(clock.now(), 1, True)
    assert decision.action is Action.CONTINUE and decision.reason is None
    assert decision.can_start and decision.autoplay_allowed
