"""Mock of the kid API (docs/kid-api.md) for developing the kid app frontend.

Serves tellybox/web/static exactly like the real web service and implements the
contract with in-memory fixtures. Put the UI in any state with POST /mock/state:

    curl -XPOST localhost:8099/mock/state -H 'content-type: application/json' \
         -d '{"tv": "ok", "time_up": false, "sky": {"fraction_left": 0.3},
              "now_playing": {"episode_id": 102, "state": "paused"}}'

`now_playing` may be null or {"episode_id", "state"} (thumb/title/show_id are filled in).
`sky` is merged; `last_five` is derived from fraction_left unless given.
v2 (step 8): three profiles (1 Mila, 2 Noah with a photo, 3 Lena out of time). `sky` and `time_up`
apply to every profile that is not fixed; override single kids with
{"profiles": {"2": {"fraction_left": 0.05, "time_up": false}}}, set {"watching": [1, 2]} and
{"day": "2026-09-30"} (a new day makes the devices ask who's watching again).
The top-level sky/time_up are derived from the watchers, like the real server.
POST /mock/reset restores the initial state.

Run: .venv/bin/python scripts/kid_mock_server.py --port 8099
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import datetime
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "tellybox" / "web" / "static"

LONG_TITLE = ("The Very Long Rainy Day Picnic That Went All the Way to the Seaside, "
              "Up the Lighthouse and Home Again Before Bedtime")
SHOWS = [
    # id, title, base colour, has artwork, episode titles (KA-10 captions)
    (1, "Paw Patrol", "E85D75", True,
     ["Pups Save a Kitten", "The Big Race", "Snow Day", "Pups and the Pirate Treasure",
      "Lighthouse Rescue", "Jungle Trouble", "Pups Save the Parade", "The Missing Bell"]),
    # 203 has an empty title and 206 a very long one: every caption state on one page.
    (2, "Bluey", "4C8BF5", True,
     ["Magic Xylophone", "Hospital", "", "Keepy Uppy", "Shadowlands", LONG_TITLE,
      "Camping", "Bike", "Grannies"]),
    (3, "Peppa Pig", "F29CB8", True,
     ["Muddy Puddles", LONG_TITLE, "Mr Dinosaur Is Lost", "Best Friend", "Polly Parrot",
      "Hide and Seek", "The Playgroup", "Bicycles"]),
    (4, "Hey Duggee", "F2A93B", False,  # no artwork: exercises the placeholder
     ["The Stick Badge", "The Cake Badge", "The Singing Badge", "The Tooth Badge",
      "The Paint Badge", "The Bug Badge", "The Kite Badge"]),
]
MISSING_THUMBS = {403, 405}  # episodes whose thumbnail 404s

EPISODES: dict[int, dict] = {}
SHOW_EPISODES: dict[int, list[int]] = {}
for show_id, _title, _c, _a, ep_titles in SHOWS:
    SHOW_EPISODES[show_id] = []
    for n, ep_title in enumerate(ep_titles, start=1):
        ep_id = show_id * 100 + n
        EPISODES[ep_id] = {"episode_id": ep_id, "show_id": show_id, "title": ep_title,
                           "progress": None, "finished": False}
        SHOW_EPISODES[show_id].append(ep_id)

for ep_id in (101, 102, 103, 201, 202, 301):
    EPISODES[ep_id].update(progress=1.0, finished=True)
for ep_id, p in ((104, 0.42), (203, 0.15), (302, 0.8), (401, 0.6)):
    EPISODES[ep_id]["progress"] = p

# id, name, built-in avatar, has an uploaded photo, continue-watching episodes (resume, then next)
PROFILES = [
    (1, "Mila", "fox", False, [(104, "resume"), (302, "resume"), (204, "next"), (203, "resume"), (401, "resume"), (303, "next")]),
    (2, "Noah", "bear", True, [(401, "resume"), (105, "next"), (302, "resume")]),
    (3, "Lena", "rabbit", False, [(203, "resume"), (302, "resume")]),
]
PROFILE_IDS = [p[0] for p in PROFILES]
FIXED_NIGHT = {3}  # out of time in the initial state; plain sky/time_up posts leave it alone


def _kid(fraction, time_up=False):
    return {"fraction_left": fraction, "last_five": fraction is not None and 0 < fraction <= 0.1,
            "unlimited": False, "time_up": time_up}


def _initial() -> dict:
    return {
        "tv": "ok",
        "now_playing": None,
        "watching": [],
        "sky": {"fraction_left": 0.92, "last_five": False, "unlimited": False},
        "time_up": False,
        "profiles": {"1": _kid(0.92), "2": _kid(0.55), "3": _kid(0.0, True)},
        "day": datetime.date.today().isoformat(),
    }


INITIAL_STATE = _initial()

IMG_DIR = Path(tempfile.mkdtemp(prefix="tellybox-mock-img-"))


def _shade(hex_: str, f: float) -> str:
    r, g, b = (int(hex_[i:i + 2], 16) for i in (0, 2, 4))
    if f >= 0:
        r, g, b = (int(c + (255 - c) * f) for c in (r, g, b))
    else:
        r, g, b = (int(c * (1 + f)) for c in (r, g, b))
    return f"0x{r:02X}{g:02X}{b:02X}"


def _make_jpg(path: Path, base: str, seed: int, big: bool) -> None:
    w, h = 640, 360
    x = 60 + (seed * 97) % 420
    boxes = [
        f"drawbox=x=0:y={h * 2 // 3}:w={w}:h={h // 3}:color={_shade(base, -0.35)}:t=fill",
        f"drawbox=x={(seed * 53) % 500}:y=40:w=90:h=90:color=0xFFE08A:t=fill",
        f"drawbox=x={x}:y={h // 3}:w=110:h=150:color={_shade(base, 0.55)}:t=fill",
        f"drawbox=x={x + 25}:y={h // 3 + 30}:w=20:h=20:color=0x1E2A5A:t=fill",
        f"drawbox=x={x + 65}:y={h // 3 + 30}:w=20:h=20:color=0x1E2A5A:t=fill",
    ]
    if big:
        boxes.append(f"drawbox=x={(x + 250) % 520}:y={h // 3 + 40}:w=90:h=110:color={_shade(base, 0.3)}:t=fill")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x{base}:s={w}x{h}",
         "-vf", ",".join(boxes), "-frames:v", "1", "-q:v", "4", str(path)],
        check=True,
    )


def make_images() -> None:
    for pid, _n, _a, photo, _c in PROFILES:
        if photo:
            _make_jpg(IMG_DIR / f"profile-{pid}.jpg", "F2A93B", pid * 11, big=False)
    for show_id, _t, base, has_art, _n in SHOWS:
        if has_art:
            _make_jpg(IMG_DIR / f"show-{show_id}.jpg", base, show_id * 7, big=True)
        for i, ep_id in enumerate(SHOW_EPISODES[show_id]):
            if ep_id not in MISSING_THUMBS:
                _make_jpg(IMG_DIR / f"episode-{ep_id}.jpg", base, ep_id + i * 3, big=False)


def show_title(show_id: int) -> str:
    return next(s[1] for s in SHOWS if s[0] == show_id)


def tile(ep_id: int) -> dict:
    e = EPISODES[ep_id]
    return {**e, "thumb": f"/img/episode/{ep_id}.jpg"}


def reduce_group(profiles: dict, ids: list[int]) -> tuple[dict, bool]:
    """Sky and time_up for a group: lowest fraction, last five if any, out of time if any."""
    ms = [profiles[str(i)] for i in ids if str(i) in profiles]
    if not ms:
        return {"fraction_left": 1.0, "last_five": False, "unlimited": False}, False
    unlimited = all(m["unlimited"] for m in ms)
    fr = [m["fraction_left"] for m in ms if not m["unlimited"] and m["fraction_left"] is not None]
    sky = {"fraction_left": None if unlimited else (min(fr) if fr else 1.0),
           "last_five": (not unlimited) and any(m["last_five"] for m in ms), "unlimited": unlimited}
    return sky, any(m["time_up"] for m in ms)


def derive(state: dict) -> None:
    """The top-level sky/time_up describe the current watchers (the first kid when nobody watches)."""
    ids = state["watching"] or PROFILE_IDS[:1]
    state["sky"], state["time_up"] = reduce_group(state["profiles"], ids)


def parse_group(raw: str | list | None) -> list[int]:
    """`?profiles=1,3` or a JSON list; anything else is a 400 (docs/kid-api.md)."""
    if raw is None or raw == "":
        return PROFILE_IDS[:1]
    try:
        ids = [int(x) for x in (raw.split(",") if isinstance(raw, str) else raw)]
    except (TypeError, ValueError):
        raise HTTPException(400, "bad_profiles") from None
    if not 1 <= len(ids) <= 20 or any(i not in PROFILE_IDS for i in ids) or len(set(ids)) != len(ids):
        raise HTTPException(400, "bad_profiles")
    return ids


class Hub:
    def __init__(self) -> None:
        self.state = copy.deepcopy(INITIAL_STATE)
        self.queues: set[asyncio.Queue] = set()
        self._settle: asyncio.Task | None = None

    def publish(self) -> None:
        for q in list(self.queues):
            q.put_nowait(copy.deepcopy(self.state))

    def set_now_playing(self, ep_id: int | None, state: str = "playing") -> None:
        if ep_id is None:
            self.state["now_playing"] = None
            return
        e = EPISODES[ep_id]
        self.state["now_playing"] = {"episode_id": ep_id, "show_id": e["show_id"],
                                     "thumb": f"/img/episode/{ep_id}.jpg", "title": e["title"],
                                     "state": state}

    def settle_later(self, target: str, delay: float) -> None:
        if self._settle:
            self._settle.cancel()

        async def run() -> None:
            await asyncio.sleep(delay)
            if self.state["now_playing"]:
                self.state["now_playing"]["state"] = target
                self.publish()

        self._settle = asyncio.create_task(run())


hub = Hub()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/api/kid/profiles")
def profiles() -> list[dict]:
    out = []
    for pid, name, avatar, photo, _cont in PROFILES:
        st = hub.state["profiles"][str(pid)]
        out.append({"profile_id": pid, "name": name, "picture": f"/img/profile/{pid}.jpg" if photo else None,
                    "avatar": avatar, **st})
    return out


@app.get("/api/kid/home")
def home(profiles: str | None = None) -> dict:
    ids = parse_group(profiles)
    cont, seen = [], set()
    for pid, _n, _a, _p, items in PROFILES:  # merged by the admin's order here; real server: by recency
        if pid not in ids:
            continue
        for ep_id, kind in items:
            if ep_id not in seen:
                seen.add(ep_id)
                cont.append({**tile(ep_id), "kind": kind})
    shows = [{"show_id": s[0], "artwork": f"/img/show/{s[0]}.jpg", "title": s[1]} for s in SHOWS]
    return {"continue": cont, "shows": shows}


@app.get("/api/kid/shows/{show_id}")
def show(show_id: int, profiles: str | None = None) -> dict:
    parse_group(profiles)
    if show_id not in SHOW_EPISODES:
        raise HTTPException(404, "not_found")
    return {"show_id": show_id, "artwork": f"/img/show/{show_id}.jpg", "title": show_title(show_id),
            "episodes": [tile(e) for e in SHOW_EPISODES[show_id]]}


@app.get("/api/kid/state")
def state() -> dict:
    return hub.state


@app.get("/api/kid/events")
async def events(request: Request) -> StreamingResponse:
    q: asyncio.Queue = asyncio.Queue()
    hub.queues.add(q)

    async def gen():
        try:
            yield f"data: {json.dumps(hub.state)}\n\n"
            while True:
                try:
                    s = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(s)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hub.queues.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/kid/play")
async def play(request: Request) -> JSONResponse:
    body = await request.json()
    ep_id = body.get("episode_id")
    try:
        ids = parse_group(body.get("profile_ids") or None)
    except HTTPException:
        return JSONResponse({"detail": "bad_profiles"}, status_code=400)
    await asyncio.sleep(0.4)  # feel the in-flight state
    if ep_id not in EPISODES:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    if any(hub.state["profiles"][str(i)]["time_up"] for i in ids):
        return JSONResponse(hub.state, status_code=409)
    if hub.state["tv"] != "ok":
        return JSONResponse(hub.state, status_code=503)
    hub.state["watching"] = ids
    derive(hub.state)
    hub.set_now_playing(ep_id, "loading")
    hub.publish()
    hub.settle_later("playing", 2.5)
    return JSONResponse(hub.state)


async def _toggle(target: str) -> JSONResponse:
    await asyncio.sleep(0.3)
    if hub.state["tv"] != "ok":
        return JSONResponse(hub.state, status_code=503)
    if hub.state["now_playing"]:
        hub.state["now_playing"]["state"] = target
        hub.publish()
    return JSONResponse(hub.state)


@app.post("/api/kid/pause")
async def pause() -> JSONResponse:
    return await _toggle("paused")


@app.post("/api/kid/resume")
async def resume() -> JSONResponse:
    return await _toggle("playing")


@app.get("/img/episode/{ep_id}.jpg")
def episode_img(ep_id: int) -> FileResponse:
    p = IMG_DIR / f"episode-{ep_id}.jpg"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@app.get("/img/profile/{pid}.jpg")
def profile_img(pid: int) -> FileResponse:
    p = IMG_DIR / f"profile-{pid}.jpg"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@app.get("/img/show/{show_id}.jpg")
def show_img(show_id: int) -> FileResponse:
    p = IMG_DIR / f"show-{show_id}.jpg"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


def _fix_kid(k: dict, patch: dict) -> None:
    k.update(patch)
    if k.get("unlimited"):
        k["fraction_left"], k["last_five"] = None, False
    elif "last_five" not in patch:
        f = k.get("fraction_left")
        k["last_five"] = f is not None and 0 < f <= 0.1


@app.post("/mock/state")
async def mock_state(request: Request) -> dict:
    body = await request.json()
    s = hub.state
    if "tv" in body:
        s["tv"] = body["tv"]
    for pid in PROFILE_IDS:  # sky/time_up posts apply to every kid that is not fixed at night
        if pid in FIXED_NIGHT:
            continue
        kid = s["profiles"][str(pid)]
        if "time_up" in body:
            kid["time_up"] = bool(body["time_up"])
        if "sky" in body:
            _fix_kid(kid, body["sky"])
    for pid, patch in (body.get("profiles") or {}).items():
        _fix_kid(s["profiles"][str(pid)], patch)
    if "watching" in body:
        s["watching"] = parse_group(body["watching"]) if body["watching"] else []
    if "day" in body:
        s["day"] = body["day"]
    derive(s)
    if "now_playing" in body:
        np = body["now_playing"]
        if np is None:
            hub.set_now_playing(None)
            s["watching"] = []
            derive(s)
        else:
            hub.set_now_playing(np["episode_id"], np.get("state", "playing"))
            if not s["watching"]:
                s["watching"] = PROFILE_IDS[:1]
                derive(s)
    hub.publish()
    return s


@app.post("/mock/reset")
def mock_reset() -> dict:
    hub.state = _initial()
    hub.publish()
    return hub.state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    make_images()
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        shutil.rmtree(IMG_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
