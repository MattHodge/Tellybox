"""History page `/admin/history` (AD-4)."""

from __future__ import annotations

from tellybox import store
from tellybox.cast.controller import EndReason

from tests.web.conftest import NOW, PROFILE


def test_history_renders_with_cast_up(admin, admin_env):
    r = admin.get("/admin/history")
    assert r.status_code == 200
    assert "History" in r.text


def test_history_renders_with_cast_down(admin, admin_env):
    admin_env.cast.mode = "down"
    r = admin.get("/admin/history")
    assert r.status_code == 200


def test_history_shows_a_finished_episode(admin, admin_env):
    conn = admin_env.conn
    session_id = store.open_watch_session(conn, admin_env.ids.b1, [PROFILE], NOW)
    store.close_watch_session(conn, session_id, EndReason.FINISHED, NOW, 300.0)

    r = admin.get("/admin/history")
    assert r.status_code == 200
    assert "Title b1" in r.text
    assert "Bravo" in r.text
    assert "finished" in r.text.lower()


def test_history_shows_an_open_session_as_watching_now(admin, admin_env):
    conn = admin_env.conn
    store.open_watch_session(conn, admin_env.ids.b1, [PROFILE], NOW)

    r = admin.get("/admin/history")
    assert r.status_code == 200
    assert "watching now" in r.text.lower()


def test_history_shows_overrides(admin, admin_env):
    store.log_override(admin_env.conn, PROFILE, NOW.date(), "extra_minutes", 15, NOW)

    r = admin.get("/admin/history")
    assert r.status_code == 200
    assert "+15 min" in r.text
