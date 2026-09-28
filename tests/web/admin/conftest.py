"""Admin test fixtures: an app with a password, a fake clock, and signed-in / anonymous clients.

Builds on tests/web/conftest.py (config, lib, fake_cast). Page tests use `admin` (signed in,
sends a same-origin Origin header on every request) and `admin_env` for the pieces.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tellybox.clock import FakeClock
from tellybox.web.app import create_app
from tests.web.conftest import NOW

PASSWORD = "correct horse battery staple"
ORIGIN = "http://testserver"


@pytest.fixture
def admin_config(config):
    return dataclasses.replace(config, admin_password=PASSWORD)


@pytest.fixture
def clock():
    return FakeClock(NOW)


@pytest.fixture
def ytdlp():
    """Override in a test module with a fake that has preview(url) -> VideoInfo."""
    return SimpleNamespace()


@pytest.fixture
def admin_static(tmp_path):
    d = tmp_path / "kid-static"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html><title>Tellybox</title>")
    return d


@pytest.fixture
def admin_env(admin_config, lib, fake_cast, clock, ytdlp, admin_static):
    conn, ids = lib
    app = create_app(admin_config, conn=conn, cast=fake_cast, clock=clock, static_dir=admin_static, ytdlp=ytdlp)
    return SimpleNamespace(app=app, conn=conn, ids=ids, cast=fake_cast, clock=clock, config=admin_config, ytdlp=ytdlp)


def sign_in(client: TestClient, password: str = PASSWORD):
    return client.post("/admin/login", data={"password": password, "next": "/admin"}, follow_redirects=False)


@pytest.fixture
def anon(admin_env) -> TestClient:
    """Not signed in; sends a same-origin Origin header like a browser form post would."""
    return TestClient(admin_env.app, headers={"Origin": ORIGIN})


@pytest.fixture
def admin(admin_env) -> TestClient:
    client = TestClient(admin_env.app, headers={"Origin": ORIGIN})
    r = sign_in(client)
    assert r.status_code == 303, r.text
    return client
