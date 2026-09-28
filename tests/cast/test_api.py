"""Cast service HTTP API, with the fake Chromecast."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from tellybox import library, store
from tellybox.cast.api import create_api
from tellybox.cast.controller import CastController
from tellybox.cast.device import DeviceInfo
from tellybox.cast.fake import FakeCastDevice
from tellybox.clock import FakeClock
from tellybox.db import open_db

TV = DeviceInfo(uuid="5f0c2a17-9b3e-4d61-8a42-c7e1b0d9f3a6", name="Living Room TV", host="192.168.1.137", model="Chromecast")
OTHER = DeviceInfo(uuid="00000000-0000-0000-0000-00000000000b", name="Bedroom", host="192.168.1.140")


@pytest.fixture
async def env(tmp_path):
    conn = open_db(tmp_path / "tellybox.db")
    clock = FakeClock(datetime(2026, 9, 28, 14, 0, tzinfo=UTC))
    show_id = library.create_show(conn, "Dev show", now=clock.now())
    episode_id = library.add_episode(conn, show_id, "Episode 1", "dev/ep1.mp4", now=clock.now(), duration_s=600)
    fake = FakeCastDevice(clock)
    ctrl = CastController(conn, clock=clock, tz=ZoneInfo("Europe/Amsterdam"), media_base_url="http://tv.test:8080",
                          secret=b"s", device=fake)
    await ctrl.start(run_loops=False)
    made = []

    async def discover():
        return [TV, OTHER]

    def factory(info):
        dev = FakeCastDevice(clock, info=info)
        made.append(dev)
        return dev

    app = create_api(ctrl, conn, discover=discover, device_factory=factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cast") as client:
        yield {"client": client, "ctrl": ctrl, "fake": fake, "conn": conn, "episode": episode_id, "made": made}


async def test_state(env):
    r = await env["client"].get("/state")
    assert r.status_code == 200
    assert r.json()["now_playing"] is None
    assert r.json()["timer"]["can_start"] is True


async def test_play_pause_stop(env):
    c = env["client"]
    r = await c.post("/play", json={"episode_id": env["episode"]})
    assert r.status_code == 200
    assert r.json()["now_playing"]["episode_id"] == env["episode"]
    assert (await c.post("/pause")).status_code == 200
    assert (await c.post("/stop")).status_code == 200
    assert env["ctrl"].current is None


async def test_play_unknown_episode(env):
    r = await env["client"].post("/play", json={"episode_id": 999})
    assert r.status_code == 404


async def test_play_refused_when_blocked(env):  # KA-9, WT-7
    c = env["client"]
    assert (await c.post("/overrides", json={"kind": "block"})).status_code == 200
    r = await c.post("/play", json={"episode_id": env["episode"]})
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "blocked"


async def test_override_validation(env):
    c = env["client"]
    assert (await c.post("/overrides", json={"kind": "bogus"})).status_code == 422
    assert (await c.post("/overrides", json={"kind": "extra_minutes"})).status_code == 422
    r = await c.post("/overrides", json={"kind": "extra_minutes", "value": 15})
    assert r.status_code == 200
    assert r.json()["timer"]["profiles"][0]["extra_s"] == 900


async def test_command_error_is_502(env):
    env["fake"].fail_next_command = True
    r = await env["client"].post("/play", json={"episode_id": env["episode"]})
    assert r.status_code == 502


async def test_devices_listed_and_selected(env):  # PB-1
    c = env["client"]
    r = await c.get("/devices")
    assert [d["uuid"] for d in r.json()["devices"]] == [TV.uuid, OTHER.uuid]
    assert (await c.post("/devices/select", json={"uuid": "nope"})).status_code == 404
    r = await c.post("/devices/select", json={"uuid": OTHER.uuid})
    assert r.status_code == 200
    assert store.selected_device(env["conn"]).uuid == OTHER.uuid
    assert env["ctrl"].device is env["made"][0]
    await env["ctrl"].stop_service()
