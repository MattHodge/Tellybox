"""Kid app API (docs/kid-api.md): library queries, the live KidState and the routes.

No login (NF-1), so everything here only ever exposes visible content: hidden shows,
hidden (incl. held) episodes and episodes of hidden shows are never listed, playable
or served as images (KA-4).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from tellybox import library
from tellybox.config import Config
from tellybox.web.cast_client import CastNotFound, CastUnavailable, TimeUp
from tellybox.web.hub import KidHub, sse_stream, unreachable

log = logging.getLogger(__name__)

CONTINUE_MAX = 8  # KA-3
RESUME_MIN_S = 10.0  # below this an episode counts as not started (PB-4)
LAST_FIVE_S = 300  # KA-8
PLAYER_STATES = {"loading", "playing", "paused", "buffering"}
IMAGE_CACHE = {"Cache-Control": "max-age=3600"}

_VISIBLE = "e.hidden = 0 AND s.hidden = 0"


def household_profile_id(conn: sqlite3.Connection) -> int:
    """v1 has a single household profile; v2 passes the picked profile instead."""
    return conn.execute("SELECT MIN(id) FROM profile").fetchone()[0]


def _thumb(episode_id: int) -> str:
    return f"/img/episode/{episode_id}.jpg"


def _tile(row: sqlite3.Row) -> dict:
    pos, duration = row["position_s"], row["duration_s"]
    progress = None if pos is None or not duration else round(min(max(pos / duration, 0.0), 1.0), 3)
    return {"episode_id": row["id"], "show_id": row["show_id"], "thumb": _thumb(row["id"]), "title": row["title"],
            "progress": progress, "finished": bool(row["finished"])}


def _show(row: sqlite3.Row) -> dict:
    return {"show_id": row["id"], "artwork": f"/img/show/{row['id']}.jpg", "title": row["name"]}


# --------------------------------------------------------------------------- queries (KA-3, KA-4, PB-4)


def list_shows(conn: sqlite3.Connection) -> list[dict]:
    """Visible shows with at least one visible episode, in admin order."""
    rows = conn.execute(
        """SELECT s.id, s.name FROM show s
           WHERE s.hidden = 0 AND EXISTS (SELECT 1 FROM episode e WHERE e.show_id = s.id AND e.hidden = 0)
           ORDER BY s.sort_order, s.id"""
    ).fetchall()
    return [_show(r) for r in rows]


def get_show(conn: sqlite3.Connection, show_id: int, profile_id: int | None = None) -> dict | None:
    row = conn.execute("SELECT id, name FROM show WHERE id = ? AND hidden = 0", (show_id,)).fetchone()
    if row is None:
        return None
    return {**_show(row), "episodes": show_episodes(conn, show_id, profile_id)}


def show_episodes(conn: sqlite3.Connection, show_id: int, profile_id: int | None = None) -> list[dict]:
    """Visible episodes in episode order, with the profile's progress."""
    profile_id = profile_id if profile_id is not None else household_profile_id(conn)
    rows = conn.execute(
        f"""SELECT e.id, e.show_id, e.title, e.duration_s, p.position_s, p.finished
            FROM episode e JOIN show s ON s.id = e.show_id
            LEFT JOIN playback_position p ON p.episode_id = e.id AND p.profile_id = ?
            WHERE e.show_id = ? AND {_VISIBLE}
            ORDER BY e.sort_order, e.id""",
        (profile_id, show_id),
    ).fetchall()
    return [_tile(r) for r in rows]


def _episode_tile(conn: sqlite3.Connection, episode_id: int, profile_id: int) -> dict | None:
    row = conn.execute(
        f"""SELECT e.id, e.show_id, e.title, e.duration_s, p.position_s, p.finished
            FROM episode e JOIN show s ON s.id = e.show_id
            LEFT JOIN playback_position p ON p.episode_id = e.id AND p.profile_id = ?
            WHERE e.id = ? AND {_VISIBLE}""",
        (profile_id, episode_id),
    ).fetchone()
    return _tile(row) if row else None


def continue_watching(conn: sqlite3.Connection, profile_id: int | None = None, limit: int = CONTINUE_MAX) -> list[dict]:
    """KA-3, PB-4: episodes to resume, plus the next episode of shows whose last watched one was finished.

    Most recently watched first; each episode at most once.
    """
    profile_id = profile_id if profile_id is not None else household_profile_id(conn)
    rows = conn.execute(
        """SELECT e.id, e.show_id, e.hidden, p.position_s, p.finished, p.updated_at
           FROM playback_position p JOIN episode e ON e.id = p.episode_id JOIN show s ON s.id = e.show_id
           WHERE p.profile_id = ? AND s.hidden = 0
           ORDER BY p.updated_at DESC, e.id DESC""",
        (profile_id,),
    ).fetchall()
    unfinished = {r["id"] for r in rows if not r["finished"]}
    picks: list[tuple[str, int]] = []  # (kind, episode_id), already in updated_at order
    seen_shows: set[int] = set()
    for r in rows:
        if not r["finished"] and not r["hidden"] and r["position_s"] >= RESUME_MIN_S:
            picks.append(("resume", r["id"]))
        if r["show_id"] in seen_shows:
            continue
        seen_shows.add(r["show_id"])  # only the show's most recently watched episode decides "next"
        if r["finished"]:
            nxt = library.next_episode(conn, r["id"])  # skips hidden episodes
            if nxt is not None and nxt.id not in unfinished:
                picks.append(("next", nxt.id))
    tiles: list[dict] = []
    added: set[int] = set()
    for kind, episode_id in picks:
        if episode_id in added:
            continue
        tile = _episode_tile(conn, episode_id, profile_id)
        if tile is None:
            continue
        added.add(episode_id)
        tiles.append({**tile, "kind": kind})
        if len(tiles) == limit:
            break
    return tiles


def episode_is_visible(conn: sqlite3.Connection, episode_id: int) -> bool:
    return conn.execute(
        f"SELECT 1 FROM episode e JOIN show s ON s.id = e.show_id WHERE e.id = ? AND {_VISIBLE}", (episode_id,)
    ).fetchone() is not None


def episode_image_paths(conn: sqlite3.Connection, episode_id: int) -> list[str]:
    row = conn.execute(
        f"SELECT e.thumbnail_path FROM episode e JOIN show s ON s.id = e.show_id WHERE e.id = ? AND {_VISIBLE}",
        (episode_id,),
    ).fetchone()
    return [row[0]] if row and row[0] else []


def show_image_paths(conn: sqlite3.Connection, show_id: int) -> list[str]:
    """Candidates in order: the show's artwork, then visible episodes' thumbnails (episode order).

    Empty for hidden shows and shows without visible episodes, which the kid never sees.
    """
    show = conn.execute("SELECT artwork_path FROM show WHERE id = ? AND hidden = 0", (show_id,)).fetchone()
    if show is None:
        return []
    thumbs = [r[0] for r in conn.execute(
        "SELECT thumbnail_path FROM episode WHERE show_id = ? AND hidden = 0 ORDER BY sort_order, id", (show_id,)
    )]
    if not thumbs:
        return []
    return [p for p in [show["artwork_path"], *thumbs] if p]


# --------------------------------------------------------------------------- KidState (KA-6..KA-9)


def _fraction_left(conn: sqlite3.Connection, timer: dict, remaining_s: float) -> float:
    allowance = {r[0]: r[1] * 60.0 for r in conn.execute("SELECT id, daily_allowance_min FROM profile")}
    limited = [p for p in timer.get("profiles") or [] if not p.get("unlimited") and p.get("profile_id") in allowance]

    def fraction(left: float, total: float) -> float:
        return min(max(left / total, 0.0), 1.0) if total > 0 else 0.0

    if len(limited) > 1:  # v2: several profiles watching; the one with the least left decides
        return min(fraction(allowance[p["profile_id"]] + p["extra_s"] - p["used_s"], allowance[p["profile_id"]] + p["extra_s"])
                   for p in limited)
    if limited:
        return fraction(remaining_s, allowance[limited[0]["profile_id"]] + limited[0]["extra_s"])
    return fraction(remaining_s, allowance.get(household_profile_id(conn), 0.0))


def kid_state(conn: sqlite3.Connection, cast: dict) -> dict:
    """Reduce the cast service's state to what the kid screen shows; no device or admin details."""
    timer = cast.get("timer") or {}
    remaining = timer.get("remaining_s")
    if remaining is None:
        sky = {"fraction_left": None, "last_five": False, "unlimited": True}
    else:
        sky = {"fraction_left": round(_fraction_left(conn, timer, remaining), 3),
               "last_five": remaining <= LAST_FIVE_S, "unlimited": False}
    np = cast.get("now_playing")
    now_playing = None
    if np:
        now_playing = {"episode_id": np["episode_id"], "show_id": np["show_id"], "thumb": _thumb(np["episode_id"]),
                       "title": np.get("title") or "",
                       "state": np.get("state") if np.get("state") in PLAYER_STATES else "loading"}
    return {
        "tv": "ok" if cast.get("connection") == "CONNECTED" else "unreachable",
        "now_playing": now_playing,
        "sky": sky,
        "time_up": bool(cast.get("time_up")),
    }


# --------------------------------------------------------------------------- routes


class PlayRequest(BaseModel):
    episode_id: int


def create_router(config: Config, conn: sqlite3.Connection, cast, hub: KidHub,
                  resolve: Callable[[Path, str], Path | None]) -> APIRouter:
    # All handlers are async so the shared sqlite connection is only used from the event loop.
    router = APIRouter()

    def reduce(state: dict, status: int = 200) -> JSONResponse:
        return JSONResponse(kid_state(conn, state), status_code=status)

    def not_found() -> HTTPException:
        return HTTPException(404, "not_found")

    async def command(name: str, call: Callable[[], Awaitable[dict]]) -> JSONResponse:
        try:
            return reduce(await call())
        except TimeUp as exc:  # KA-9
            return reduce(exc.state, 409)
        except CastUnavailable as exc:
            log.warning("kid %s: TV unreachable: %s", name, exc)
            return JSONResponse(unreachable(hub.state), status_code=503)

    @router.get("/api/kid/home")
    async def home() -> dict:
        return {"continue": continue_watching(conn), "shows": list_shows(conn)}

    @router.get("/api/kid/shows/{show_id}")
    async def show(show_id: int) -> dict:
        page = get_show(conn, show_id)
        if page is None:
            raise not_found()
        return page

    @router.get("/api/kid/state")
    async def state() -> JSONResponse:
        try:
            return reduce(await cast.state())
        except CastUnavailable:
            return JSONResponse(unreachable(hub.state))

    @router.get("/api/kid/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(sse_stream(hub), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/api/kid/play")
    async def play(req: PlayRequest) -> JSONResponse:  # KA-5
        if not episode_is_visible(conn, req.episode_id):
            raise not_found()
        try:
            return await command("play", lambda: cast.play(req.episode_id))
        except CastNotFound:
            raise not_found() from None

    @router.post("/api/kid/pause")
    async def pause() -> JSONResponse:  # KA-6
        return await command("pause", cast.pause)

    @router.post("/api/kid/resume")
    async def resume() -> JSONResponse:
        return await command("resume", cast.resume)

    def image(candidates: list[str]) -> FileResponse:
        for rel in candidates:
            path = resolve(config.media_dir, rel)
            if path is not None:
                return FileResponse(path, headers=IMAGE_CACHE)
        raise not_found()

    @router.get("/img/episode/{episode_id}.jpg")
    async def episode_image(episode_id: int) -> FileResponse:
        return image(episode_image_paths(conn, episode_id))

    @router.get("/img/show/{show_id}.jpg")
    async def show_image(show_id: int) -> FileResponse:
        return image(show_image_paths(conn, show_id))

    return router
