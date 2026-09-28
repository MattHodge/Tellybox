import threading

from tellybox import db


def test_migrations_apply_once(tmp_path):
    conn = db.open_db(tmp_path / "t.db")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == db.migrations()[-1][0]
    assert db.migrate(conn) == version  # idempotent
    assert conn.execute("SELECT count(*) FROM profile").fetchone()[0] == 1  # household profile (v1)


def test_concurrent_startup_migrates_once(tmp_path):  # web, cast and worker start together
    # Each round starts from a fresh file: switching it to WAL is where concurrent starts collided.
    for round_ in range(20):
        path = tmp_path / f"t{round_}.db"
        errors = []

        def start():
            try:
                db.open_db(path)
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=start) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert db.connect(path).execute("SELECT count(*) FROM profile").fetchone()[0] == 1


def test_per_thread_connection_keeps_threads_apart(tmp_path):
    """The web service runs sync handlers in a thread pool; one shared connection mixed their queries."""
    path = tmp_path / "t.db"
    db.open_db(path).close()
    conn = db.PerThreadConnection(path)
    conn.execute("BEGIN IMMEDIATE")
    seen = {}

    def other_thread():
        seen["in_transaction"] = conn.in_transaction
        seen["reset_time"] = conn.execute("SELECT reset_time FROM settings WHERE id = 1").fetchone()["reset_time"]

    t = threading.Thread(target=other_thread)
    t.start()
    t.join()
    conn.execute("COMMIT")
    assert seen == {"in_transaction": False, "reset_time": "04:00"}
