"""Runtime configuration from environment variables (NF-9: state on mounted volumes)."""

from __future__ import annotations

import os
import secrets
import socket
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _local_zone_name() -> str:
    if tz := os.environ.get("TELLYBOX_TZ") or os.environ.get("TZ"):
        return tz
    try:
        return Path("/etc/timezone").read_text().strip()
    except OSError:
        pass
    try:
        target = os.readlink("/etc/localtime")
        return target.split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


def lan_ip() -> str:
    """IP of the interface that routes outward; the address the Chromecast can reach."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("1.1.1.1", 80))
        return s.getsockname()[0]


def load_or_create_secret(path: Path) -> bytes:
    """Shared signing secret (NF-3). Created once; safe if web and cast race."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes().strip()
    with os.fdopen(fd, "wb") as f:
        key = secrets.token_hex(32).encode()
        f.write(key)
    return key


def admin_password_from_env(env: dict[str, str]) -> str | None:
    """TELLYBOX_ADMIN_PASSWORD, or the contents of TELLYBOX_ADMIN_PASSWORD_FILE (AD-1). None if unset/empty."""
    value = env.get("TELLYBOX_ADMIN_PASSWORD")
    if not value and (file := env.get("TELLYBOX_ADMIN_PASSWORD_FILE")):
        value = Path(file).read_text().rstrip("\r\n")
    return value or None


@dataclass(frozen=True)
class Config:
    db_path: Path
    media_dir: Path
    data_dir: Path
    tz: ZoneInfo
    web_host: str
    web_port: int
    cast_api_host: str
    cast_api_port: int
    media_base_url: str  # how the Chromecast reaches the web service, e.g. http://192.168.1.10:8080
    secret: bytes
    admin_password: str | None = field(default=None, repr=False)  # None: admin is locked
    version: str = "dev"  # TELLYBOX_VERSION, set by the Dockerfile's APP_VERSION build arg

    @classmethod
    def from_env(cls) -> Config:
        env = os.environ
        data_dir = Path(env.get("TELLYBOX_DATA_DIR", "data"))
        web_port = int(env.get("TELLYBOX_WEB_PORT", "8080"))
        base_url = env.get("TELLYBOX_MEDIA_BASE_URL") or f"http://{lan_ip()}:{web_port}"
        return cls(
            db_path=Path(env.get("TELLYBOX_DB", data_dir / "tellybox.db")),
            media_dir=Path(env.get("TELLYBOX_MEDIA_DIR", "media")),
            data_dir=data_dir,
            tz=ZoneInfo(_local_zone_name()),
            web_host=env.get("TELLYBOX_WEB_HOST", "0.0.0.0"),
            web_port=web_port,
            cast_api_host=env.get("TELLYBOX_CAST_API_HOST", "127.0.0.1"),
            cast_api_port=int(env.get("TELLYBOX_CAST_API_PORT", "8081")),
            media_base_url=base_url.rstrip("/"),
            secret=load_or_create_secret(Path(env.get("TELLYBOX_SECRET_FILE", data_dir / "secret.key"))),
            admin_password=admin_password_from_env(env),
            version=env.get("TELLYBOX_VERSION", "dev"),
        )
