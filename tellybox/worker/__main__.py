"""Entry point of the worker service: `python -m tellybox.worker`."""

from __future__ import annotations

import logging
import signal

from tellybox.clock import SystemClock
from tellybox.config import Config
from tellybox.db import open_db
from tellybox.ingest import JobRunner
from tellybox.worker import Worker
from tellybox.ytdlp import YtDlp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = Config.from_env()
    conn = open_db(config.db_path)
    tools_dir = config.data_dir / "tools" / "yt-dlp"
    runner = JobRunner(conn=conn, media_dir=config.media_dir, tools_dir=tools_dir, ytdlp=YtDlp(tools_dir), clock=SystemClock())
    worker = Worker(runner, config.tz)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop.set())
    worker.run_forever()


if __name__ == "__main__":
    main()
