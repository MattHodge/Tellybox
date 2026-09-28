# Kid API contract (step 4; tile titles shown since step 7)

The kid app (static files in `tellybox/web/static/`) talks only to these endpoints of the
`web` service. No login (NF-1). Only visible content ever appears: hidden shows/episodes and
held downloads are never listed, playable or served as images.

## Types

```jsonc
// KidState: everything the kid screen shows live (KA-6..KA-9)
{
  "tv": "ok" | "unreachable",              // cast service down, or Chromecast not connected
  "now_playing": null | {
    "episode_id": 4, "show_id": 2,
    "thumb": "/img/episode/4.jpg",
    "title": "Alongside",                   // screen-reader label of the now-playing thumbnail; not shown
    "state": "loading" | "playing" | "paused" | "buffering"
  },
  "sky": {
    "fraction_left": 0.62,                  // 0..1 of today's allowance (+extra) left; null when unlimited
    "last_five": false,                     // <= 5 min left (and not unlimited)
    "unlimited": false
  },
  "time_up": false                          // picks disabled (KA-9); may be true while an episode finishes (grace)
}

// Tile
{ "episode_id": 4, "show_id": 2, "thumb": "/img/episode/4.jpg",
  "title": "Alongside",                     // shown as a small caption under the thumbnail, max two lines
                                            // (KA-10), and the tile's screen-reader label; may be ""
  "progress": 0.42,                         // 0..1 watched, null if never started
  "finished": false }
```

## Endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/` | the kid app shell (`static/index.html`) |
| GET | `/static/...` | static assets |
| GET | `/manifest.webmanifest` | web app manifest |
| GET | `/api/kid/home` | `{"continue": [Tile & {"kind": "resume" \| "next"}], "shows": [{"show_id", "artwork": "/img/show/2.jpg", "title"}]}`; the show `title` is shown as a small caption (KA-10) and is the tile's screen-reader label |
| GET | `/api/kid/shows/{id}` | `{"show_id", "artwork", "title", "episodes": [Tile]}` in episode order; 404 if hidden/missing |
| GET | `/api/kid/state` | KidState |
| GET | `/api/kid/events` | SSE, one `data: <KidState JSON>` per change, `: keepalive` comments every 15 s; first event immediately |
| POST | `/api/kid/play` `{"episode_id": 4}` | 200 KidState; 404 `{"detail": "not_found"}` if not visible; 409 KidState when time is up; 503 KidState when the TV is unreachable |
| POST | `/api/kid/pause`, `/api/kid/resume` | 200 KidState; 503 KidState when unreachable |
| GET | `/img/episode/{id}.jpg`, `/img/show/{id}.jpg` | image; 404 unless visible. Show artwork falls back to the first visible episode's thumbnail; if nothing is available, 404 (the frontend draws a placeholder). |
