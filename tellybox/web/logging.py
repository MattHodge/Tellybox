"""Access-log redaction (NF-3): signed media URLs never land in logs whole.

`/media/{episode_id}/{expires_at}/{sig}.mp4` is a bearer credential (the
signature is the only thing checked); the episode id is still useful for
diagnostics, so only the expiry and signature are blanked out.
"""

from __future__ import annotations

import logging
import re

_MEDIA_PATH_RE = re.compile(r"(/media/\d+)/\d+/[A-Za-z0-9_-]+\.mp4")
_REPLACEMENT = "\\1/…/<redacted>.mp4"  # \1 keeps the episode id; … replaces expiry + signature


def _redact(text: str) -> str:
    return _MEDIA_PATH_RE.sub(_REPLACEMENT, text)


class RedactMediaSignatures(logging.Filter):
    """Rewrites signed media paths wherever they appear in a record's args or message."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: (_redact(v) if isinstance(v, str) else v) for k, v in record.args.items()}
        return True
