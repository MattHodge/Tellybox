"""Consistent SQLite backups (NF-9), run nightly by the worker.

Uses sqlite3's online backup API, which is safe to run against a database other
services are writing to at the same time (CLAUDE.md: only the cast service writes
the timer/history tables, but web and worker also hold connections) as long as the
database is in WAL mode, which tellybox.db.connect() sets. The copy is checked with
PRAGMA integrity_check before it's kept; retention only runs after a good backup.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

FILENAME_FORMAT = "tellybox-%Y%m%d-%H%M.db"
GLOB = "tellybox-*.db"


class BackupError(Exception):
    """The copy failed its integrity check; nothing was pruned."""


def _integrity_check(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def _copy(db_path: Path, tmp_path: Path) -> None:
    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(tmp_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _prune(dest: Path, keep: int) -> None:
    """Keep the newest `keep` backups (by name, which sorts by date); delete the rest."""
    backups = sorted(dest.glob(GLOB), reverse=True)
    for old in backups[keep:]:
        old.unlink()


def backup(db_path: Path, dest: Path, now: datetime, tz: ZoneInfo, keep: int = 14) -> Path:
    """Write a consistent copy of db_path into dest, verify it, then prune old backups.

    The file is named tellybox-YYYYMMDD-HHMM.db from `now` converted to `tz` (local time).
    A rerun in the same minute replaces the existing file atomically. Raises BackupError
    (and leaves existing backups untouched) if the copy fails PRAGMA integrity_check.
    """
    dest.mkdir(parents=True, exist_ok=True)
    name = now.astimezone(tz).strftime(FILENAME_FORMAT)
    final = dest / name
    tmp = dest / f".{name}.tmp"

    _copy(db_path, tmp)

    result = _integrity_check(tmp)
    if result != "ok":
        tmp.unlink(missing_ok=True)
        raise BackupError(f"integrity check failed for {name}: {result}")

    tmp.replace(final)  # atomic rename; replaces a same-minute rerun
    log.info("backup: %s (%d bytes)", final.name, final.stat().st_size)

    _prune(dest, keep)
    return final
