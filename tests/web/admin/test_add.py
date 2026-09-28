"""Add video (/admin/add): preview then approve or hold (CI-1)."""

from __future__ import annotations

import pytest

from tellybox import library
from tellybox.ytdlp import Chapter, VideoInfo, YtDlpError

URL = "https://www.youtube.com/watch?v=abc123"


def info(**kw) -> VideoInfo:
    return VideoInfo(
        youtube_id="abc123", url=URL, title="Episode one", channel_id="UCkids", channel_name="Kids Channel",
        duration_s=125.0, thumbnail_url="https://i.ytimg.com/vi/abc123/hq.jpg",
        chapters=kw.pop("chapters", []), is_live=False, **kw,
    )


class FakeYtDlp:
    def __init__(self) -> None:
        self.error: YtDlpError | None = None
        self.info = info()
        self.calls: list[str] = []

    def preview(self, url: str) -> VideoInfo:
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.info


@pytest.fixture
def ytdlp():
    return FakeYtDlp()


def _preview(admin, url: str = URL):
    return admin.post("/admin/add/preview", data={"url": url})


def _preview_id(text: str) -> str:
    marker = 'name="preview_id" value="'
    start = text.index(marker) + len(marker)
    return text[start:text.index('"', start)]


def test_add_page_renders(admin):
    r = admin.get("/admin/add")
    assert r.status_code == 200
    assert "Add a video" in r.text


def test_preview_shows_video_details(admin, ytdlp):
    r = _preview(admin)
    assert r.status_code == 200
    assert "Episode one" in r.text
    assert "Kids Channel" in r.text
    assert "new show" in r.text
    assert ytdlp.calls == [URL]


def test_preview_shows_chapters(admin, ytdlp):
    ytdlp.info = info(chapters=[Chapter(0, 30, "Intro"), Chapter(30, 60, "Song")])
    r = _preview(admin)
    assert "Intro" in r.text and "Song" in r.text


def test_preview_finds_existing_show_by_channel(admin, admin_env, ytdlp):
    library.create_show(admin_env.conn, "Existing Kids Show", now=admin_env.clock.now(), youtube_channel_id="UCkids")
    r = _preview(admin)
    assert "Existing Kids Show" in r.text
    assert "new show" not in r.text


def test_preview_rejects_empty_url(admin, ytdlp):
    r = admin.post("/admin/add/preview", data={"url": ""})
    assert r.status_code == 422
    assert ytdlp.calls == []


def test_preview_rejects_non_http_url(admin, ytdlp):
    r = admin.post("/admin/add/preview", data={"url": "javascript:alert(1)"})
    assert r.status_code == 422
    assert ytdlp.calls == []


def test_preview_shows_permanent_ytdlp_error(admin, ytdlp):
    ytdlp.error = YtDlpError("Video unavailable", retryable=False)
    r = _preview(admin)
    assert r.status_code == 422
    assert "Video unavailable" in r.text
    assert "later" not in r.text.lower()


def test_preview_notes_retryable_ytdlp_error(admin, ytdlp):
    ytdlp.error = YtDlpError("HTTP Error 503", retryable=True)
    r = _preview(admin)
    assert r.status_code == 422
    assert "HTTP Error 503" in r.text
    assert "later" in r.text.lower()


def test_add_queues_download_and_redirects_to_jobs(admin, admin_env, ytdlp):
    pid = _preview_id(_preview(admin).text)
    r = admin.post("/admin/add", data={"preview_id": pid, "action": "add"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/jobs"
    row = admin_env.conn.execute("SELECT publish, status FROM source_video WHERE youtube_id = 'abc123'").fetchone()
    assert row["publish"] == "publish" and row["status"] == "queued"


def test_add_and_hold_keeps_it_held(admin, admin_env, ytdlp):
    pid = _preview_id(_preview(admin).text)
    admin.post("/admin/add", data={"preview_id": pid, "action": "hold"}, follow_redirects=False)
    row = admin_env.conn.execute("SELECT publish FROM source_video WHERE youtube_id = 'abc123'").fetchone()
    assert row["publish"] == "hold"


def test_add_unknown_preview_id_is_422(admin):
    r = admin.post("/admin/add", data={"preview_id": "does-not-exist", "action": "add"})
    assert r.status_code == 422
    assert "expired" in r.text.lower()


def test_add_already_added_shows_links_and_422(admin, admin_env, ytdlp):
    pid1 = _preview_id(_preview(admin).text)
    admin.post("/admin/add", data={"preview_id": pid1, "action": "add"})
    pid2 = _preview_id(_preview(admin).text)
    r = admin.post("/admin/add", data={"preview_id": pid2, "action": "add"})
    assert r.status_code == 422
    assert "/admin/jobs" in r.text
    assert "/admin/library" in r.text


def test_add_reuses_preview_id_only_once(admin, ytdlp):
    pid = _preview_id(_preview(admin).text)
    r1 = admin.post("/admin/add", data={"preview_id": pid, "action": "add"}, follow_redirects=False)
    assert r1.status_code == 303
    r2 = admin.post("/admin/add", data={"preview_id": pid, "action": "add"})
    assert r2.status_code == 422
    assert "expired" in r2.text.lower()
