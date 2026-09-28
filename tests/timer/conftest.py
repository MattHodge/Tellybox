"""Fixtures for the watch-timer tests (WT-*)."""

from datetime import time

import pytest

from tellybox.clock import FakeClock
from tellybox.timer import ProfilePolicy, TimerSettings, WatchTimer

from timer_helpers import AMS, START, policy


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def settings() -> TimerSettings:
    return TimerSettings(reset_time=time(4, 0), tz=AMS)


@pytest.fixture
def make_timer(clock, settings):
    def _make(*policies: ProfilePolicy, usages=(), snapshot=None, **policy_kwargs) -> WatchTimer:
        policies = list(policies) or [policy(**policy_kwargs)]
        return WatchTimer(settings, policies, list(usages), clock.now(), snapshot=snapshot)

    return _make
