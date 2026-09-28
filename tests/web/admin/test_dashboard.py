"""Dashboard `/admin` (AD-3, WT-7, NF-11): what's on the TV, overrides, jobs, disk (AD-3)."""

from __future__ import annotations

import pytest

from tellybox import jobs
from tellybox.jobs import JobStatus, JobType
from tellybox.web.cast_client import CastUnavailable

from tests.web.conftest import PROFILE


def test_dashboard_renders_with_cast_up(admin, admin_env):
    r = admin.get("/admin")
    assert r.status_code == 200
    assert "What's on the TV" in r.text


def test_dashboard_shows_version(admin, admin_env):
    r = admin.get("/admin")
    assert r.status_code == 200
    assert f"Tellybox {admin_env.config.version}" in r.text


def test_dashboard_renders_with_cast_down(admin, admin_env):
    admin_env.cast.mode = "down"
    r = admin.get("/admin")
    assert r.status_code == 200
    assert "unreachable" in r.text.lower()


def test_dashboard_shows_now_playing_and_profile_time(admin, admin_env, mkstate, mkplaying):
    admin_env.cast.current = mkstate(
        now_playing=mkplaying(admin_env.ids.b1, admin_env.ids.bravo, title="Hospital"),
        used_s=600, remaining_s=2400,
    )
    r = admin.get("/admin")
    assert r.status_code == 200
    assert "Hospital" in r.text
    assert "Bravo" in r.text  # show name looked up from the episode


@pytest.mark.parametrize("state, header, label", [
    ("playing", None, "playing"),
    ("loading", "nl", "starten…"),
    ("playing", "nl", "speelt af"),
    ("paused", "de-DE", "pausiert"),
])
def test_dashboard_player_state_is_translated(admin, admin_env, mkstate, mkplaying, state, header, label):
    """NF-13: the cast service sends lowercase states (loading, playing, buffering, paused)."""
    admin_env.cast.current = mkstate(now_playing=mkplaying(admin_env.ids.b1, admin_env.ids.bravo, state=state))
    r = admin.get("/admin", headers={"Accept-Language": header} if header else {})
    assert f'<span class="badge">{label}</span>' in r.text


def test_dashboard_shows_failed_and_active_jobs(admin, admin_env, clock):
    jid_failed = jobs.enqueue(admin_env.conn, JobType.DOWNLOAD, 1, now=clock.now())
    jobs.fail(admin_env.conn, jid_failed, "boom", now=clock.now(), retryable=False)
    jobs.enqueue(admin_env.conn, JobType.DOWNLOAD, 2, now=clock.now())
    jobs.claim_next(admin_env.conn, now=clock.now())

    r = admin.get("/admin")
    assert r.status_code == 200
    assert "1 failed job" in r.text
    assert "download" in r.text.lower()


def test_dashboard_api_json(admin, admin_env, clock):
    admin_env.conn.execute(
        "INSERT INTO tool_version (name, version, path, checked_at, updated_at) VALUES ('yt-dlp', '2026.09.01', NULL, ?, ?)",
        ("2026-09-28T12:00:00.000Z", "2026-09-28T12:00:00.000Z"),
    )
    r = admin.get("/admin/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["ytdlp_version"] == "2026.09.01"
    assert body["jobs"] == {"failed": [], "active": []}
    assert "media_bytes" in body["disk"]


def test_stop_calls_cast(admin, admin_env):
    r = admin.post("/admin/stop", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"
    assert ("stop",) in admin_env.cast.calls


def test_stop_when_cast_unreachable_flashes_not_500(admin, admin_env):
    admin_env.cast.mode = "down"
    r = admin.post("/admin/stop", follow_redirects=False)
    assert r.status_code == 303
    follow = admin.get(r.headers["location"])
    assert "unreachable" in follow.text.lower()


def test_override_extra_minutes_calls_cast_with_kind_and_value(admin, admin_env):
    r = admin.post(
        "/admin/overrides", data={"kind": "extra_minutes", "value": "15", "profile_id": str(PROFILE)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert ("override", "extra_minutes", 15, PROFILE) in admin_env.cast.calls


def test_override_unlimited_toggle(admin, admin_env):
    r = admin.post(
        "/admin/overrides", data={"kind": "unlimited", "value": "1", "profile_id": str(PROFILE)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert ("override", "unlimited", 1, PROFILE) in admin_env.cast.calls


def test_override_stop_now(admin, admin_env):
    r = admin.post("/admin/overrides", data={"kind": "stop_now", "profile_id": str(PROFILE)}, follow_redirects=False)
    assert r.status_code == 303
    assert ("override", "stop_now", None, PROFILE) in admin_env.cast.calls


def test_override_refused_flashes_not_500(admin, admin_env):
    admin_env.cast.mode = "invalid"
    r = admin.post(
        "/admin/overrides", data={"kind": "extra_minutes", "value": "-1", "profile_id": str(PROFILE)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    follow = admin.get(r.headers["location"])
    assert follow.status_code == 200


def test_override_when_cast_unreachable_flashes_not_500(admin, admin_env):
    admin_env.cast.mode = "down"
    r = admin.post(
        "/admin/overrides", data={"kind": "stop_now", "profile_id": str(PROFILE)}, follow_redirects=False,
    )
    assert r.status_code == 303
    follow = admin.get(r.headers["location"])
    assert "unreachable" in follow.text.lower()


def test_events_relays_scripted_cast_stream(admin, admin_env, mkstate):
    admin_env.cast.streams = [[mkstate(remaining_s=42)]]
    with admin.stream("GET", "/admin/events") as r:
        assert r.status_code == 200
        lines = []
        for line in r.iter_lines():
            lines.append(line)
            if line.startswith("data:"):
                break
    data_lines = [ln for ln in lines if ln.startswith("data:")]
    assert data_lines
    assert '"remaining_s": 42' in data_lines[0] or "42" in data_lines[0]
