"""Run the web service: `python -m tellybox.web`."""

from __future__ import annotations

import logging
import sys

import uvicorn

from tellybox.config import Config
from tellybox.web.app import create_app
from tellybox.web.logging import RedactMediaSignatures

LOG_FORMAT = "%(asctime)s level=%(levelname)s logger=%(name)s %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Structured-ish logs to stdout (NF-11); signed media paths never land in them whole (NF-3)."""
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stdout, force=True)
    logging.getLogger("uvicorn.access").addFilter(RedactMediaSignatures())


def main() -> None:
    setup_logging()
    config = Config.from_env()
    logging.getLogger("tellybox.web").info(
        "starting web host=%s port=%s media_dir=%s media_base_url=%s",
        config.web_host, config.web_port, config.media_dir, config.media_base_url,
    )
    app = create_app(config)  # one DB connection per handler thread
    # log_config=None: uvicorn's loggers propagate to the root handler set up above.
    # Live streams (SSE) never close by themselves; don't let them hold up a restart. Browsers reconnect.
    uvicorn.run(app, host=config.web_host, port=config.web_port, log_config=None, proxy_headers=False,
                timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
