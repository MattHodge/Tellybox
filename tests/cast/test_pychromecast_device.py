import asyncio
import threading
from types import SimpleNamespace
from uuid import UUID

import pychromecast
import pytest
from pychromecast.error import NotConnected, RequestFailed, RequestTimeout

from tellybox.cast import pychromecast_device as mod
from tellybox.cast.device import (
    DEFAULT_MEDIA_RECEIVER as DMR,
    ConnectionState,
    ConnectionStatus,
    DeviceInfo,
    LoadFailed,
    MediaStatus,
    PlayerState,
    ReceiverStatus,
)
from tellybox.cast.pychromecast_device import CastCommandError, PyChromecastDevice, discover

UUID1 = "11111111-2222-3333-4444-555555555555"
INFO = DeviceInfo(uuid=UUID1, name="Living Room TV", host="192.168.1.137")


class StubMC:
    def __init__(self):
        self.calls = []
        self.listeners = []
        self.fail: dict[str, Exception] = {}

    def register_status_listener(self, listener):
        self.listeners.append(listener)

    def _call(self, name, *args, **kw):
        self.calls.append((name, args, kw))
        if name in self.fail:
            raise self.fail[name]

    def play_media(self, *a, **kw): self._call("play_media", *a, **kw)
    def pause(self): self._call("pause")
    def play(self): self._call("play")
    def stop(self): self._call("stop")
    def update_status(self): self._call("update_status")


class StubCast:
    def __init__(self, host="192.168.1.137", wait_error=None):
        self.cast_info = SimpleNamespace(host=host, port=8009, friendly_name="Living Room TV", model_name="Chromecast")
        self.media_controller = StubMC()
        self.status_listeners, self.connection_listeners, self.launch_listeners = [], [], []
        self.wait_error = wait_error
        self.quit_error = None
        self.calls = []

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self.wait_error:
            raise self.wait_error

    def register_status_listener(self, l): self.status_listeners.append(l)
    def register_connection_listener(self, l): self.connection_listeners.append(l)
    def register_launch_error_listener(self, l): self.launch_listeners.append(l)

    def quit_app(self):
        self.calls.append(("quit_app",))
        if self.quit_error:
            raise self.quit_error

    def disconnect(self, timeout=None):
        self.calls.append(("disconnect",))


@pytest.fixture
def cast(monkeypatch):
    stub = StubCast()
    seen = []

    def from_host(host, **kw):
        seen.append(host)
        return stub

    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", from_host)
    stub.seen = seen
    return stub


def in_thread(fn, *args):
    t = threading.Thread(target=fn, args=args)
    t.start()
    t.join()


async def next_events(dev, n):
    it = dev.events()
    return [await asyncio.wait_for(anext(it), 1) for _ in range(n)]


def cast_status(app_id, session_id, name=None):
    return SimpleNamespace(app_id=app_id, session_id=session_id, display_name=name)


def media_status(state, content_id="http://x/a.mp4", t=0.0, duration=600.0, idle_reason=None, msid=1):
    return SimpleNamespace(player_state=state, content_id=content_id, current_time=t, duration=duration,
                           idle_reason=idle_reason, media_session_id=msid)


async def test_connect_direct_to_remembered_host(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect(timeout=3.0)
    assert cast.seen == [("192.168.1.137", 8009, UUID(UUID1), None, "Living Room TV")]
    assert cast.calls[0] == ("wait", 3.0)
    assert len(cast.status_listeners) == len(cast.connection_listeners) == len(cast.media_controller.listeners) == 1


async def test_connect_falls_back_to_discovery_by_uuid(monkeypatch, cast):
    cast.wait_error = RequestTimeout("wait", 1)
    found = StubCast(host="192.168.1.50")
    browser = SimpleNamespace(stopped=False)
    browser.stop_discovery = lambda: setattr(browser, "stopped", True)
    args = {}

    def listed(**kw):
        args.update(kw)
        return [found], browser

    monkeypatch.setattr(pychromecast, "get_listed_chromecasts", listed)
    dev = PyChromecastDevice(INFO)
    await dev.connect(timeout=10.0)
    assert args["uuids"] == [UUID(UUID1)]
    assert ("disconnect",) in cast.calls
    assert dev.info.host == "192.168.1.50" and dev.info.model == "Chromecast"
    assert found.status_listeners and found.media_controller.listeners
    await dev.close()
    assert browser.stopped and ("disconnect",) in found.calls


async def test_connect_without_fallback_raises(cast):
    cast.wait_error = RequestTimeout("wait", 1)
    with pytest.raises(CastCommandError):
        await PyChromecastDevice(INFO, discovery_fallback=False).connect(timeout=1.0)
    assert ("disconnect",) in cast.calls


async def test_fallback_finds_nothing(monkeypatch, cast):
    cast.wait_error = RequestTimeout("wait", 1)
    browser = SimpleNamespace(stop_discovery=lambda: None)
    monkeypatch.setattr(pychromecast, "get_listed_chromecasts", lambda **kw: ([], browser))
    with pytest.raises(CastCommandError):
        await PyChromecastDevice(INFO).connect(timeout=1.0)


async def test_listener_callbacks_become_events_in_order(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    conn, recv, med = cast.connection_listeners[0], cast.status_listeners[0], cast.media_controller.listeners[0]

    def fire():
        conn.new_connection_status(SimpleNamespace(status="CONNECTED", address=None, service=None))
        recv.new_cast_status(cast_status(DMR, "s1", "Default Media Receiver"))
        med.new_media_status(media_status("BUFFERING", t=None))
        med.new_media_status(media_status("PLAYING", t=12.5))
        med.new_media_status(media_status("WEIRD"))
        med.new_media_status(media_status("IDLE", t=0, idle_reason="FINISHED"))
        med.load_media_failed(3, 104)
        conn.new_connection_status(SimpleNamespace(status="FAILED_RESOLVE", address=None, service=None))
        conn.new_connection_status(SimpleNamespace(status="LOST", address=None, service=None))

    in_thread(fire)
    assert await next_events(dev, 9) == [
        ConnectionStatus(ConnectionState.CONNECTED),
        ReceiverStatus(DMR, "s1", "Default Media Receiver"),
        MediaStatus(PlayerState.BUFFERING, "http://x/a.mp4", 0.0, 600.0, None, 1),
        MediaStatus(PlayerState.PLAYING, "http://x/a.mp4", 12.5, 600.0, None, 1),
        MediaStatus(PlayerState.UNKNOWN, "http://x/a.mp4", 0.0, 600.0, None, 1),
        MediaStatus(PlayerState.IDLE, "http://x/a.mp4", 0.0, 600.0, "FINISHED", 1),
        LoadFailed(104),
        ConnectionStatus(ConnectionState.FAILED),
        ConnectionStatus(ConnectionState.LOST),
    ]
    assert dev.receiver == ReceiverStatus(DMR, "s1", "Default Media Receiver")
    assert dev.media.player_state == PlayerState.IDLE


async def test_launch_error_becomes_load_failed(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    in_thread(cast.launch_listeners[0].new_launch_error, SimpleNamespace(reason="X", app_id=DMR, request_id=1))
    assert await next_events(dev, 1) == [LoadFailed(None)]


async def test_play_uses_buffered_mp4(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    await dev.play("http://x/a.mp4", title="Ep", start_s=42.0)
    await dev.play("http://x/b.mp4")
    mc = cast.media_controller
    assert mc.calls == [
        ("play_media", ("http://x/a.mp4", "video/mp4"), {"title": "Ep", "stream_type": "BUFFERED", "current_time": 42.0}),
        ("play_media", ("http://x/b.mp4", "video/mp4"), {"title": None, "stream_type": "BUFFERED", "current_time": None}),
    ]


async def test_simple_commands(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    await dev.pause()
    await dev.resume()
    await dev.request_status()
    assert [c[0] for c in cast.media_controller.calls] == ["pause", "play", "update_status"]


async def test_stop_stops_media_then_quits_app(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    await dev.stop()
    assert [c[0] for c in cast.media_controller.calls] == ["stop"]
    assert cast.calls[-1] == ("quit_app",)


async def test_stop_tolerates_no_media_session(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    cast.media_controller.fail["stop"] = RequestFailed("stop")
    cast.quit_error = RequestFailed("quit app")
    await dev.stop()
    assert cast.calls[-1] == ("quit_app",)


async def test_stop_raises_when_quit_times_out(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    cast.quit_error = RequestTimeout("quit app", 10)
    with pytest.raises(CastCommandError):
        await dev.stop()


@pytest.mark.parametrize("exc", [NotConnected(), RequestTimeout("pause", 10), RequestFailed("pause")])
async def test_errors_become_cast_command_error(cast, exc):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    cast.media_controller.fail["pause"] = exc
    with pytest.raises(CastCommandError) as err:
        await dev.pause()
    assert err.value.__cause__ is exc


async def test_commands_before_connect_raise():
    with pytest.raises(CastCommandError):
        await PyChromecastDevice(INFO).pause()


async def test_close_disconnects_and_ignores_late_callbacks(cast):
    dev = PyChromecastDevice(INFO)
    await dev.connect()
    await dev.close()
    assert ("disconnect",) in cast.calls
    in_thread(cast.status_listeners[0].new_cast_status, cast_status(None, None))
    await asyncio.sleep(0.01)
    assert dev.receiver is None


async def test_discover(monkeypatch):
    infos = [SimpleNamespace(uuid=UUID(UUID1), friendly_name="Living Room TV", host="192.168.1.137",
                             port=8009, model_name="Chromecast")]
    browser = SimpleNamespace(stopped=False)
    browser.stop_discovery = lambda: setattr(browser, "stopped", True)
    got = {}

    def fake_discover(**kw):
        got.update(kw)
        return infos, browser

    monkeypatch.setattr(pychromecast.discovery, "discover_chromecasts", fake_discover)
    assert await discover(timeout=1.0, known_hosts=["192.168.1.137"]) == [
        DeviceInfo(UUID1, "Living Room TV", "192.168.1.137", 8009, "Chromecast")
    ]
    assert got == {"timeout": 1.0, "known_hosts": ["192.168.1.137"]} and browser.stopped


def test_module_exports():
    assert issubclass(mod.CastCommandError, Exception)
