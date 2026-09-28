"""KidHub: relays the cast service's state stream to kid pages (KA-7)."""

import asyncio
import json

import pytest

from tellybox.web.cast_client import CastUnavailable
from tellybox.web.hub import KidHub, sse_stream


def reduce(s: dict) -> dict:
    """Stand-in reduction: keeps the test independent of the DB."""
    return {"tv": "ok", "now_playing": s.get("np"), "sky": {"fraction_left": s["f"], "last_five": False,
            "unlimited": False}, "time_up": s.get("up", False)}


def drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def run_until(hub: KidHub, cond, timeout: float = 2.0) -> None:
    hub.start()
    try:
        async with asyncio.timeout(timeout):
            while not cond():
                await asyncio.sleep(0.005)
    finally:
        await hub.stop()


async def test_initial_state_is_unreachable(fake_cast):
    hub = KidHub(fake_cast, reduce)
    assert hub.state["tv"] == "unreachable"
    assert hub.state["now_playing"] is None
    q = hub.subscribe()
    assert q.get_nowait() == hub.state  # first event immediately


async def test_broadcasts_to_all_subscribers_and_dedupes(fake_cast):
    fake_cast.streams = [[{"f": 0.5}, {"f": 0.5}, {"f": 0.4, "np": {"episode_id": 1}}]]
    hub = KidHub(fake_cast, reduce, min_backoff=0.01, max_backoff=0.01)
    q1, q2 = hub.subscribe(), hub.subscribe()
    await run_until(hub, lambda: fake_cast.events_calls >= 2)
    for q in (q1, q2):
        got = drain(q)
        assert [(s["tv"], s["sky"]["fraction_left"]) for s in got] == [
            ("unreachable", None), ("ok", 0.5), ("ok", 0.4), ("unreachable", 0.4)]
        # Stream ended: unreachable, keeps the last known sky, drops now playing.
        assert got[-1]["now_playing"] is None
        assert got[2]["now_playing"] == {"episode_id": 1}


async def test_unreachable_then_recovers_with_backoff(fake_cast):
    fake_cast.streams = [CastUnavailable("down"), CastUnavailable("down"), [{"f": 0.9, "up": True}],
                         CastUnavailable("down")]
    delays = []

    async def sleep(d):
        delays.append(d)
        await asyncio.sleep(0)

    hub = KidHub(fake_cast, reduce, min_backoff=1.0, max_backoff=5.0, sleep=sleep)
    q = hub.subscribe()
    await run_until(hub, lambda: len(delays) >= 7)
    # 1, 2 while down; reset to 1 after events arrived, then 2, 4, 5, 5 ...
    assert delays[:7] == [1.0, 2.0, 1.0, 2.0, 4.0, 5.0, 5.0]
    got = drain(q)
    assert [s["tv"] for s in got] == ["unreachable", "ok", "unreachable"]
    assert got[-1]["time_up"] is True  # last known time_up survives the outage
    assert hub.state == got[-1]


async def test_unexpected_errors_do_not_kill_the_loop(fake_cast):
    fake_cast.streams = [ValueError("bad json"), [{"f": 1.0}]]
    hub = KidHub(fake_cast, reduce, min_backoff=0.001, max_backoff=0.001)
    await run_until(hub, lambda: fake_cast.events_calls >= 3)
    assert hub.state["sky"]["fraction_left"] == 1.0


async def test_slow_subscriber_drops_oldest(fake_cast):
    hub = KidHub(fake_cast, reduce, queue_size=3)
    q = hub.subscribe()
    for i in range(10):
        hub.publish(reduce({"f": i / 10}))
    got = drain(q)
    assert [s["sky"]["fraction_left"] for s in got] == [0.7, 0.8, 0.9]


async def test_unsubscribe(fake_cast):
    hub = KidHub(fake_cast, reduce)
    q = hub.subscribe()
    hub.unsubscribe(q)
    hub.publish(reduce({"f": 0.1}))
    assert [s["tv"] for s in drain(q)] == ["unreachable"]


async def test_stop_without_start(fake_cast):
    await KidHub(fake_cast, reduce).stop()


def parse(chunk: str) -> dict:
    assert chunk.startswith("data: ") and chunk.endswith("\n\n")
    return json.loads(chunk[6:])


async def test_sse_stream_first_event_immediately_then_changes_and_keepalive(fake_cast):
    hub = KidHub(fake_cast, reduce)
    gen = sse_stream(hub, keepalive_s=0.05)
    async with asyncio.timeout(2):
        assert parse(await anext(gen)) == hub.state
        assert len(hub._subscribers) == 1
        hub.publish(reduce({"f": 0.3}))
        assert parse(await anext(gen))["sky"]["fraction_left"] == 0.3
        assert await anext(gen) == ": keepalive\n\n"
        await gen.aclose()
    assert not hub._subscribers
