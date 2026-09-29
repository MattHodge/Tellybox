"""Live kid state (KA-7): one relay of the cast service's event stream, fanned out
to every open kid page over SSE.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from tellybox.web.cast_client import CastUnavailable

log = logging.getLogger(__name__)

SSE_KEEPALIVE_S = 15.0

# Before the first cast state arrives nothing is known: TV unreachable, sky unknown.
INITIAL_STATE: dict = {
    "tv": "unreachable",
    "now_playing": None,
    "sky": {"fraction_left": None, "last_five": False, "unlimited": False},
    "time_up": False,
    "watching": [],
    "profiles": {},
    "day": None,
}


def unreachable(state: dict) -> dict:
    """The TV can't be reached: keep the last known sky and time_up, drop now playing."""
    return {**state, "tv": "unreachable", "now_playing": None}


class KidHub:
    def __init__(
        self,
        cast,
        reduce: Callable[[dict], dict],
        *,
        min_backoff: float = 1.0,
        max_backoff: float = 5.0,
        queue_size: int = 20,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.cast = cast
        self.reduce = reduce
        self.min_backoff = min_backoff
        self.max_backoff = max_backoff
        self.queue_size = queue_size
        self._sleep = sleep
        self.state: dict = INITIAL_STATE
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------ fan-out

    def subscribe(self) -> asyncio.Queue:
        """A queue that starts with the current state, then gets every change."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        q.put_nowait(self.state)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, state: dict) -> None:
        if state == self.state:
            return
        self.state = state
        for q in self._subscribers:
            if q.full():  # a slow page only needs the latest state
                q.get_nowait()
            q.put_nowait(state)

    # ------------------------------------------------------------------ relay loop

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="kid-hub")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run(self) -> None:
        delay = self.min_backoff
        down = False  # log once per outage, not on every retry
        while True:
            try:
                async for cast_state in self.cast.events():
                    self.publish(self.reduce(cast_state))
                    delay, down = self.min_backoff, False
                reason = "event stream ended"
            except CastUnavailable as exc:
                reason = str(exc)
            except Exception as exc:  # keep relaying whatever goes wrong
                log.exception("kid hub relay failed")
                reason = repr(exc)
            if not down:
                log.warning("cast service unreachable, retrying: %s", reason)
                down = True
            self.publish(unreachable(self.state))
            await self._sleep(delay)
            delay = min(delay * 2, self.max_backoff)


async def sse_stream(hub: KidHub, keepalive_s: float = SSE_KEEPALIVE_S) -> AsyncIterator[str]:
    """SSE body: the current state immediately, then one event per change (KA-7)."""
    q = hub.subscribe()
    try:
        while True:
            try:
                state = await asyncio.wait_for(q.get(), keepalive_s)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(state)}\n\n"
    finally:
        hub.unsubscribe(q)
