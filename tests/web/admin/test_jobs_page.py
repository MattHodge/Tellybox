"""Jobs (/admin/jobs): queue status, retry and the yt-dlp update button (CI-3, CI-5)."""

from __future__ import annotations

from tellybox import ingest, jobs
from tellybox.db import to_db
from tellybox.jobs import JobType
from tellybox.ytdlp import VideoInfo


def info(youtube_id: str = "abc123", **kw) -> VideoInfo:
    return VideoInfo(
        youtube_id=youtube_id, url=f"https://www.youtube.com/watch?v={youtube_id}", title="Episode one",
        channel_id="UCkids", channel_name="Kids Channel", duration_s=100.0, thumbnail_url=None,
        chapters=[], is_live=False, **kw,
    )


def test_jobs_page_lists_download_job_with_its_video_title(admin, admin_env):
    ingest.add(admin_env.conn, info(), publish=True, now=admin_env.clock.now())
    r = admin.get("/admin/jobs")
    assert r.status_code == 200
    assert "Episode one" in r.text
    assert "queued" in r.text


def test_jobs_page_shows_error_and_attempts_of_a_failed_job(admin, admin_env):
    conn, clock = admin_env.conn, admin_env.clock
    _, job_id = ingest.add(conn, info(), publish=True, now=clock.now())
    jobs.fail(conn, job_id, "Private video", now=clock.now(), retryable=False)
    r = admin.get("/admin/jobs")
    assert "Private video" in r.text
    assert "failed" in r.text


def test_jobs_page_shows_installed_ytdlp_version(admin, admin_env):
    now = to_db(admin_env.clock.now())
    admin_env.conn.execute(
        "INSERT INTO tool_version (name, version, path, checked_at, updated_at) VALUES ('yt-dlp', '2026.09.01', NULL, ?, ?)",
        (now, now),
    )
    r = admin.get("/admin/jobs")
    assert "2026.09.01" in r.text


def test_jobs_api_returns_json(admin, admin_env):
    ingest.add(admin_env.conn, info(), publish=True, now=admin_env.clock.now())
    r = admin.get("/admin/api/jobs")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["status"] == "queued"
    assert data[0]["label"] == "Episode one"
    assert data[0]["retryable"] is False


def test_retry_requeues_a_failed_job(admin, admin_env):
    conn, clock = admin_env.conn, admin_env.clock
    _, job_id = ingest.add(conn, info(), publish=True, now=clock.now())
    jobs.fail(conn, job_id, "boom", now=clock.now(), retryable=False)
    r = admin.post(f"/admin/jobs/{job_id}/retry", follow_redirects=False)
    assert r.status_code == 303
    assert jobs.get(conn, job_id).status.value == "queued"


def test_retry_on_a_running_job_is_refused_without_erroring(admin, admin_env):
    conn, clock = admin_env.conn, admin_env.clock
    _, job_id = ingest.add(conn, info(), publish=True, now=clock.now())
    jobs.claim_next(conn, now=clock.now())  # now downloading, not failed
    r = admin.post(f"/admin/jobs/{job_id}/retry", follow_redirects=False)
    assert r.status_code == 303  # redirected back with a flash, not a hard error
    assert jobs.get(conn, job_id).status.value == "downloading"


def test_retry_unknown_job_is_404(admin):
    r = admin.post("/admin/jobs/999999/retry")
    assert r.status_code == 404


def test_update_ytdlp_button_queues_a_job(admin, admin_env):
    r = admin.post("/admin/jobs/update-ytdlp", follow_redirects=False)
    assert r.status_code == 303
    assert jobs.has_pending(admin_env.conn, JobType.UPDATE_YTDLP)


def test_update_ytdlp_reports_when_already_pending(admin, admin_env):
    admin.post("/admin/jobs/update-ytdlp")
    r = admin.post("/admin/jobs/update-ytdlp", follow_redirects=False)
    assert r.status_code == 303
    page = admin.get(r.headers["location"])
    assert "already pending" in page.text.lower()
