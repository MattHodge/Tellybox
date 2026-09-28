# Step 5: Admin pages (plan)

_Status: approved 2026-09-28 and built on branch `step5/admin`; real-device checks pending. Branch: `step5/admin`, one PR._

**Goal:** everything a parent does, from a phone:
- sign in;
- add videos;
- manage the library;
- set limits;
- use the overrides from anywhere over Tailscale;
- see what's playing, what's downloading and what was watched.

## Decisions already made (owner, 2026-09-27)

- **Admin password comes from an environment variable** (not a CLI command or a first-visit page).
- **Admin UI is server-rendered:** Jinja2 templates with plain forms, plus a little vanilla JS for live parts.

## Sign-in (AD-1, NF-2)

- **Password from the environment:** `TELLYBOX_ADMIN_PASSWORD`, or `TELLYBOX_ADMIN_PASSWORD_FILE` for Docker/deploy secrets.
  - At startup the web service stores an argon2id hash of it (`argon2-cffi`). The plain password isn't written anywhere else.
  - To change the password, change the variable and restart. All existing sessions end.
  - With no password configured, `/admin` shows "Admin is locked: set TELLYBOX_ADMIN_PASSWORD" and nothing else.
- **Sessions:**
  - A random token in an `HttpOnly`, `SameSite=Strict` cookie limited to `/admin`.
  - Only a hash of the token is stored in the database.
  - A session expires after 30 days without use; each visit resets the clock.
  - The cookie is marked `Secure` when the page was loaded over HTTPS (e.g. `tailscale serve`).
- **Protection:**
  - Every admin request is checked on the server.
  - Form submissions must come from the admin pages themselves (Origin check).
  - Failed logins slow down for that device's address, from 1 s up to 60 s.
- **No links between the apps:** the kid app has no link to `/admin`, and the admin pages don't expose kid-app internals.

## Pages

Server-rendered Jinja2 with plain forms, plus a little vanilla JS for the live parts. They're built phone-first and use the kid app's ink (`#1E2A5A`) and yolk (`#FFC93C`) colours in a calm, utilitarian layout.

| Page | What it does | Req |
|---|---|---|
| **Dashboard** `/admin` | • What's on the TV now, with a Stop button<br>• Today's time used and left<br>• Overrides: +15 min, +30 min, unlimited today, block today / unblock, stop now<br>• Chromecast connection<br>• Failed jobs and active downloads<br>• yt-dlp version, disk usage<br>• Updates live | AD-3, WT-7, NF-11 |
| **Add video** `/admin/add` | • Paste a URL and see the preview: thumbnail, title, channel, duration, chapters<br>• Choose **Add** or **Add and hold** | CI-1 |
| **Jobs** `/admin/jobs` | • Status and progress, updating live<br>• Error text<br>• **Retry**<br>• **Update yt-dlp** and the installed version | CI-3, CI-5 |
| **Library** `/admin/library` | • Show list with artwork, episode count and disk use<br>• Hidden and autoplay flags<br>• New show, merge shows<br>• Held downloads, each with **Publish** | CI-4, CI-6, LM-3 |
| **Show** `/admin/shows/{id}` | • Rename, autoplay, hide, delete<br>• Artwork: upload, or pick a frame from an episode<br>• Episodes in order with up/down buttons (easier on a phone than dragging)<br>• Per episode: rename, hide/unhide, move to another show, thumbnail (upload or frame), delete | LM-1..LM-4, CI-6 |
| **Settings** `/admin/settings` | • Per profile: allowance, counting mode, maximum session length<br>• Reset time, grace cap, session break<br>• Chromecast: choose from the discovered devices, with a search button | AD-2, PB-1 |
| **History** `/admin/history` | • Per day: episode, start and end, minutes counted, how it ended<br>• Overrides applied that day<br>• Last 21 days | AD-4 |

**Notes:**
- **Timer settings:** changes are saved to the database, and the cast service picks them up within 15 s (`CastController.persist` reloads policies).
- **Overrides and device selection:** these go through the cast service API (`/overrides`, `/devices`, `/devices/select`), since it's the only owner of the timer and the Chromecast.
- **Frame picking (LM-2):**
  - A preview frame at a chosen time is grabbed with ffmpeg on request.
  - **Use this frame** saves it as a JPEG.
  - Uploads (JPG/PNG/WebP, up to 5 MB) are re-encoded by ffmpeg to JPEG, at most 1280 px wide. That cleans the file and caps its size.
- **Moving episodes between shows** (the missing part of LM-1) is added to `tellybox/library.py`.
- **Out of scope for now:** the splitting profile in LM-4 belongs to v2. Per-show settings are autoplay only.

## Background tasks

- **History purge (AD-5):** the worker's daily task, which already runs at 03:00 (`tellybox/worker/__init__.py`), now also removes:
  - viewing history (`watch_session`) and override log older than 21 days;
  - timer usage rows (`daily_usage`) older than 21 days;
  - finished jobs older than 30 days.
- **Log redaction:** signed media links are masked in the web access log, e.g. `/media/4/…/<redacted>.mp4`.

## Schema (`003_admin.sql`)

- `admin_session`: token hash, created, last used.
- `login_throttle`.
- An `admin_password_hash` column on `settings`.

## Tests

- **Sign-in:**
  - login and logout;
  - the 30-day expiry and how each visit extends it;
  - changing the password ends all sessions;
  - the locked state when no password is set;
  - Origin check and login throttling;
  - every admin route refuses anyone not signed in.
- **Every page renders.** Every action checks its effect in the database, including:
  - reordering, moving and merging;
  - hiding, and publishing held downloads;
  - deleting with files;
  - settings validation, e.g. an allowance of 0 or less, or a malformed reset time.
- **Images:** frame extraction and the upload clean-up, using ffmpeg-made test files.
- **The rest:** the history query, the purge, log redaction, and overrides and device selection against a fake cast service.

## Checking it for real

1. Start the stack with `TELLYBOX_ADMIN_PASSWORD` set, and sign in from the owner's phone.
2. Add a second video through the UI and watch its progress on the Jobs page.
3. Rename and reorder, hide an episode, and check the kid app updates.
4. From the phone dashboard, use +15 min while a kid page is open; the sun should rise.
5. Block today, then unblock.
6. Check the history page shows today's viewing.
7. If Tailscale runs on the dev machine, sign in once over it as well.

## How the previous steps were run (for continuity)

- **Plan, approve, code:** each step starts with a plan the owner approves, then code on a branch with one PR.
- **Subagents:** the owner allowed subagents with a cap per step (3 for step 2, 4 for steps 3 and 4). Ask again, or use the cap they give. The pattern:
  - write the shared contract or schema first;
  - agents build separate files in parallel;
  - integrate and review yourself.
- **Real-device check with the owner:**
  - The owner has approved using the real Chromecast ("Living Room TV") and their phone.
  - Run the containers with `docker run --network host` and `:z` volume mounts on the Fedora dev box. The compose plugin isn't installed.
  - Container names: `tb-web`, `tb-cast`, `tb-worker`.
  - `./data` and `./media` hold the dev database, one real Bluey episode and three test clips.
