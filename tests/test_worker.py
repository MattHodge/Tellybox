from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tellybox import ingest, jobs
from tellybox.clock import FakeClock
from tellybox.db import open_db
from tellybox.ingest import JobRunner
from tellybox.jobs import JobType
from tellybox.worker import Worker, update_due

TZ = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
def conn(tmp_path):
    return open_db(tmp_path / "t.db")


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).astimezone(UTC)


def test_update_due_when_never_run(conn):  # CI-5
    # Recording the fallback version at startup doesn't count as an update.
    ingest.record_tool_version(conn, "yt-dlp", "2026.08.19", None, now=local(2026, 9, 28, 11))
    assert update_due(conn, local(2026, 9, 28, 12), TZ)


@pytest.mark.parametrize(
    ("checked", "now", "due"),
    [
        (local(2026, 9, 28, 3, 5), local(2026, 9, 28, 12), False),   # checked after today's 03:00
        (local(2026, 9, 27, 12), local(2026, 9, 28, 2, 59), False),  # before today's slot; yesterday's done
        (local(2026, 9, 27, 12), local(2026, 9, 28, 3, 0), True),    # today's slot reached
        (local(2026, 9, 26, 12), local(2026, 9, 28, 1), True),       # missed a day
    ],
)
def test_update_due_daily_at_three(conn, checked, now, due):
    job_id = ingest.request_ytdlp_update(conn, now=checked)
    jobs.complete(conn, job_id, now=checked)
    assert update_due(conn, now, TZ) is due


class RecordingRunner(JobRunner):
    def __init__(self, conn, clock):
        super().__init__(conn=conn, media_dir=None, tools_dir=None, ytdlp=None, clock=clock)
        self.ran = []

    def run(self, job):
        self.ran.append(job.id)
        jobs.complete(self.conn, job.id, now=self.clock.now())


def test_step_runs_one_job_and_queues_first_update(conn):
    clock = FakeClock(local(2026, 9, 28, 12))
    runner = RecordingRunner(conn, clock)
    worker = Worker(runner, TZ)
    _, job_id = ingest.add(conn, _info(), publish=True, now=clock.now())
    assert worker.step()  # never checked -> update queued, but the download was first in line
    assert runner.ran == [job_id]
    assert jobs.has_pending(conn, JobType.UPDATE_YTDLP)
    assert worker.step()
    assert not worker.step()


def test_no_auto_update_when_disabled(conn):
    clock = FakeClock(local(2026, 9, 28, 12))
    worker = Worker(RecordingRunner(conn, clock), TZ, auto_update=False)
    assert not worker.step()
    assert not jobs.has_pending(conn, JobType.UPDATE_YTDLP)


def _info():
    from tellybox.ytdlp import VideoInfo
    return VideoInfo(youtube_id="w1", url="https://www.youtube.com/watch?v=w1", title="t", channel_id="c",
                     channel_name="C", duration_s=1.0, thumbnail_url=None, chapters=[], is_live=False)


# --------------------------------------------------------------------------- purge (AD-5)


def _old_watch_session(conn, now):
    from tellybox.db import to_db
    conn.execute(
        "INSERT INTO watch_session (id, episode_id, started_at, ended_at, seconds_counted) VALUES (1, NULL, ?, ?, 0)",
        (to_db(now - timedelta(days=40)), to_db(now - timedelta(days=22))),
    )


def test_purge_runs_once_in_the_daily_update_slot_and_again_the_next(conn):
    clock = FakeClock(local(2026, 9, 28, 12))  # well after today's 03:00 slot
    _old_watch_session(conn, clock.now())
    worker = Worker(RecordingRunner(conn, clock), TZ)

    assert worker.step()  # never checked before: update queued and run, purge runs in the same slot
    assert conn.execute("SELECT count(*) FROM watch_session").fetchone()[0] == 0

    # Later the same day: the update check (and so the purge) isn't due again.
    _old_watch_session(conn, clock.now())
    clock.advance(hours=1)
    assert not worker.step()
    assert conn.execute("SELECT count(*) FROM watch_session").fetchone()[0] == 1

    # The next day's 03:00 slot: due again.
    clock.advance(days=1)
    assert worker.step()
    assert conn.execute("SELECT count(*) FROM watch_session").fetchone()[0] == 0


def test_no_auto_purge_when_disabled(conn):
    clock = FakeClock(local(2026, 9, 28, 12))
    _old_watch_session(conn, clock.now())
    worker = Worker(RecordingRunner(conn, clock), TZ, auto_purge=False)
    worker.step()
    assert conn.execute("SELECT count(*) FROM watch_session").fetchone()[0] == 1


def test_purge_runs_daily_at_03_00_without_the_ytdlp_update(conn):
    clock = FakeClock(local(2026, 9, 28, 12))
    worker = Worker(RecordingRunner(conn, clock), TZ, auto_update=False)
    _old_watch_session(conn, clock.now())
    worker.step()  # at startup
    assert conn.execute("SELECT count(*) FROM watch_session").fetchone()[0] == 0

    _old_watch_session(conn, clock.now())
    clock.set(local(2026, 9, 29, 2, 59))
    worker.step()  # still the same 03:00-to-03:00 day
    assert conn.execute("SELECT count(*) FROM watch_session").fetchone()[0] == 1
    clock.set(local(2026, 9, 29, 3, 0))
    worker.step()
    assert conn.execute("SELECT count(*) FROM watch_session").fetchone()[0] == 0
