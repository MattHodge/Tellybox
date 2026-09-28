"""Signed, expiring media URLs (NF-3).

The Chromecast cannot authenticate, so each media URL carries an HMAC over the
episode id and expiry. The signature depends only on the shared secret
(Config.secret), so URLs stay valid across process restarts, and the episode id
can be read back from any URL regardless of its token (restart recovery, NF-7;
spike finding 7).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import datetime
from urllib.parse import urlsplit

MEDIA_TTL_S = 24 * 3600
_SIG_LEN = 22  # 132 bits of HMAC-SHA256

_PATH_RE = re.compile(r"^/media/(\d+)/(\d+)/([A-Za-z0-9_-]+)\.mp4$")


def _sign(secret: bytes, episode_id: int, expires_at: int) -> str:
    mac = hmac.new(secret, f"{episode_id}:{expires_at}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()[:_SIG_LEN]


def media_path(secret: bytes, episode_id: int, expires_at: int) -> str:
    return f"/media/{episode_id}/{expires_at}/{_sign(secret, episode_id, expires_at)}.mp4"


def media_url(base_url: str, secret: bytes, episode_id: int, now: datetime, ttl_s: int = MEDIA_TTL_S) -> str:
    expires_at = int(now.timestamp()) + ttl_s
    return base_url.rstrip("/") + media_path(secret, episode_id, expires_at)


def verify(secret: bytes, episode_id: int, expires_at: int, sig: str, now: datetime) -> bool:
    if expires_at < now.timestamp():
        return False
    return hmac.compare_digest(
        _sign(secret, episode_id, expires_at).encode(), sig.encode("utf-8", "surrogateescape")
    )


def episode_id_from_url(url: str | None) -> int | None:
    """Episode id if `url` points at one of our media paths, else None (WT-9: ignore other casts)."""
    if not url:
        return None
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    m = _PATH_RE.match(path)
    return int(m.group(1)) if m else None
