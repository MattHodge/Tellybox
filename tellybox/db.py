"""SQLite access: one file holds all state (NF-9).

Plain sqlite3 with numbered SQL migrations in tellybox/migrations/NNN_name.sql,
tracked through PRAGMA user_version. Timestamps are stored as ISO-8601 UTC text.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d{3})_[\w-]+\.sql$")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(path) != ":memory:":
        _enable_wal(conn)
    return conn


def _enable_wal(conn: sqlite3.Connection, timeout_s: float = 5.0) -> None:
    """Switch to WAL, retrying while locked.

    busy_timeout doesn't cover changing the journal mode: when web, cast and worker open
    a fresh file at the same moment, all but one can get "database is locked" here.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def migrations() -> list[tuple[int, str, str]]:
    found = []
    for entry in resources.files("tellybox.migrations").iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.name, entry.read_text()))
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the resulting schema version.

    web and cast start together; the write lock is taken first and the version
    re-read inside the transaction so only one of them applies a migration.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, name, sql in migrations():
        if version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > current:
                log.info("applying migration %s", name)
                for statement in _split_sql(sql):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version}")
                current = version
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return current


def _split_sql(sql: str) -> list[str]:
    """Split a migration into statements (executescript would auto-commit)."""
    statements, buf = [], []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buf.append(line)
        if stripped.endswith(";") and sqlite3.complete_statement("\n".join(buf)):
            statements.append("\n".join(buf))
            buf = []
    if buf:
        statements.append("\n".join(buf))
    return statements


def open_db(path: Path | str) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn


class PerThreadConnection:
    """Behaves like a sqlite3.Connection, but each thread gets its own (opened on first use).

    The web service runs plain `def` handlers in a thread pool. One shared connection lets
    concurrent requests interleave statements and transactions; WAL mode lets these
    connections read and write side by side instead. The file must already be migrated.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = connect(self._path)
        return conn

    def __getattr__(self, name: str):
        return getattr(self._conn(), name)


def to_db(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).isoformat(timespec="milliseconds")


def from_db(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)
