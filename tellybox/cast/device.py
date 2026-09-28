"""The Chromecast as seen by the controller.

`CastDevice` is the only boundary to the real device. Everything above it
(controller, timer) is tested with `tellybox.cast.fake.FakeCastDevice`.

Spike findings that shaped this interface (docs/spike-casting.md):
- The device only pushes status on state changes; there is no periodic update
  while playing, so callers must track time themselves.
- Media status from *other* apps (e.g. YouTube) also arrives here; callers must
  filter on receiver session id and content id (WT-9).
- `current_time` is 0 in the IDLE/FINISHED status.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

DEFAULT_MEDIA_RECEIVER = "CC1AD845"


class PlayerState(StrEnum):
    PLAYING = "PLAYING"
    BUFFERING = "BUFFERING"
    PAUSED = "PAUSED"
    IDLE = "IDLE"
    UNKNOWN = "UNKNOWN"


class ConnectionState(StrEnum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    LOST = "LOST"
    FAILED = "FAILED"
    DISCONNECTED = "DISCONNECTED"


@dataclass(frozen=True)
class DeviceInfo:
    uuid: str
    name: str | None
    host: str
    port: int = 8009
    model: str | None = None


@dataclass(frozen=True)
class ReceiverStatus:
    """Which app runs on the device. app_id/session_id are None when idle/backdrop-less."""

    app_id: str | None
    session_id: str | None
    display_name: str | None = None


@dataclass(frozen=True)
class MediaStatus:
    player_state: PlayerState
    content_id: str | None
    current_time: float
    duration: float | None
    idle_reason: str | None = None  # FINISHED | CANCELLED | INTERRUPTED | ERROR
    media_session_id: int | None = None


@dataclass(frozen=True)
class ConnectionStatus:
    state: ConnectionState


@dataclass(frozen=True)
class LoadFailed:
    error_code: int | None = None


DeviceEvent = ReceiverStatus | MediaStatus | ConnectionStatus | LoadFailed


class CastDevice(Protocol):
    """One Chromecast. All methods are async and must not block the event loop."""

    info: DeviceInfo | None

    async def connect(self, timeout: float = 15.0) -> None:
        """Connect (and keep reconnecting in the background after losses)."""
        ...

    async def close(self) -> None: ...

    def events(self) -> AsyncIterator[DeviceEvent]:
        """Every status change, in order. Single consumer."""
        ...

    @property
    def receiver(self) -> ReceiverStatus | None:
        """Last known receiver status."""
        ...

    @property
    def media(self) -> MediaStatus | None:
        """Last known media status (may belong to another app)."""
        ...

    async def play(self, url: str, *, title: str | None = None, start_s: float = 0.0) -> None:
        """Launch the Default Media Receiver if needed and load `url` as BUFFERED video/mp4."""
        ...

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...

    async def stop(self) -> None:
        """Stop media and quit the receiver app, so the TV returns to its idle screen."""
        ...

    async def request_status(self) -> None:
        """Ask the device for a fresh media status (result arrives as an event)."""
        ...
