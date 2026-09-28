"""Consistent SQLite backups (NF-9)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tellybox import backup as backup_mod
from tellybox.db import connect

TZ = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 9, 28, 1, 30, tzinfo=UTC)  # 03:30 local (CEST, UTC+2)


def make_db(path: Path) -> None:
    """A WAL-mode db with a row written through a second connection, like web/cast/worker do."""
    conn = connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
    second = connect(path)
    second.execute("INSERT INTO t (value) VALUES ('hello')")
    second.close()
    conn.close()


def test_backup_copy_contains_the_row(tmp_path):
    db_path = tmp_path / "tellybox.db"
    dest = tmp_path / "backups"
    make_db(db_path)

    result = backup_mod.backup(db_path, dest, NOW, TZ, keep=14)

    assert result == dest / "tellybox-20260928-0330.db"
    assert result.is_file()
    copy = connect(result)
    try:
        assert copy.execute("SELECT value FROM t").fetchone()[0] == "hello"
    finally:
        copy.close()


def test_retention_keeps_newest_n_and_ignores_other_files(tmp_path):
    db_path = tmp_path / "tellybox.db"
    dest = tmp_path / "backups"
    make_db(db_path)
    dest.mkdir()
    (dest / "notes.txt").write_text("not a backup")
    for name in ("tellybox-20260921-0000.db", "tellybox-20260922-0000.db", "tellybox-20260923-0000.db"):
        (dest / name).write_text("old")

    backup_mod.backup(db_path, dest, NOW, TZ, keep=2)

    remaining = sorted(p.name for p in dest.glob("tellybox-*.db"))
    assert remaining == ["tellybox-20260923-0000.db", "tellybox-20260928-0330.db"]
    assert (dest / "notes.txt").exists()


def test_same_minute_rerun_replaces_atomically(tmp_path):
    db_path = tmp_path / "tellybox.db"
    dest = tmp_path / "backups"
    make_db(db_path)

    first = backup_mod.backup(db_path, dest, NOW, TZ, keep=14)
    conn = connect(db_path)
    conn.execute("INSERT INTO t (value) VALUES ('second')")
    conn.close()
    second = backup_mod.backup(db_path, dest, NOW, TZ, keep=14)

    assert first == second
    assert len(list(dest.glob("tellybox-*.db"))) == 1
    copy = connect(second)
    try:
        rows = [r[0] for r in copy.execute("SELECT value FROM t ORDER BY id")]
        assert rows == ["hello", "second"]
    finally:
        copy.close()


def test_failed_integrity_check_prunes_nothing_and_raises(tmp_path, monkeypatch):
    db_path = tmp_path / "tellybox.db"
    dest = tmp_path / "backups"
    make_db(db_path)
    dest.mkdir()
    (dest / "tellybox-20260101-0000.db").write_text("kept")

    monkeypatch.setattr(backup_mod, "_integrity_check", lambda path: "corrupted")

    with pytest.raises(backup_mod.BackupError):
        backup_mod.backup(db_path, dest, NOW, TZ, keep=1)

    remaining = sorted(p.name for p in dest.glob("tellybox-*.db"))
    assert remaining == ["tellybox-20260101-0000.db"]
    assert not list(dest.glob(".*.tmp"))
