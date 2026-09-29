# Step 8 handoff: subagent briefs

These go with `docs/plans/step8-profiles.md`. Three subagents, run in parallel on **Sonnet**, each in its own git worktree off the part 0 contract commit on `step8/profiles`. The controller (Opus) writes the contract first, then merges in the order A, B, C, and reviews.

## Rules for every subagent

- Read `CLAUDE.md`, `docs/plans/step8-profiles.md` (your part and part 0) and the contract files named in your brief before coding. The PRD (`docs/PRD.md`) is the source of truth; cite requirement IDs (PR-1..4, WT-*, KA-*, AD-*) in tests and comments where the surrounding code does.
- Write the tests first (TDD), then the code. No network, no real Chromecast: use the fake clock and `tellybox/cast/fake.py`.
- Run tests with the main checkout's venv from your worktree root: `/home/sander/Projects/Tellybox/.venv/bin/python -m pytest -q`. The full suite must pass before you report.
- Stay inside your files (listed below). If the contract is wrong or missing something, don't change it on your own: work around it minimally and report it.
- Match the surrounding code: its naming, comment density and idioms. No new dependencies.
- Keep private details out: no hostnames, IPs or internal domains (the repository is public).
- Commit in your worktree with a clear message ending in `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. Don't push, and don't open a PR.
- **Report back:** what you built, the test count before and after, any contract gaps, and anything you're unsure about.

## Subagent A: timer and cast service

**Files:** `tellybox/timer/`, `tellybox/cast/`, `tellybox/store.py` (position/profile helpers only), `tests/timer/`, `tests/cast/`.

**Contract to read:** the timer stubs in `tellybox/timer/watch_timer.py` and `models.py`, and `docs/cast-api.md`.

**Tasks**
1. `WatchTimer`: add watchers.
   - Only watchers accrue time, and `remaining_s`, the session max (WT-3), blocked and the grace (WT-4/5) come from the watchers.
   - Each profile gets its own viewing session (`session_start`, `inactive_since`) and its own exhaustion. A profile that stops watching starts its 15-minute break at that moment.
   - Implement `on_pick(now, profile_ids=None)`, `set_watchers`, `watchers`, `group_decision` and `profile_status`. `None` means every profile, so the existing timer tests keep passing unchanged.
2. Snapshot version 2: the watchers, per-profile sessions and per-profile exhaustion. A v1 snapshot restores with every profile as a watcher.
3. `CastController`:
   - `play(episode_id, profile_ids)` checks the ids against the `profile` table. The list must not be empty.
   - Autoplay keeps `Current.profile_ids`, and recovery calls `set_watchers`.
   - The group's resume position is the most recently updated unfinished position among the members (add a store helper).
   - Profiles deleted while watching are dropped on the next `persist`.
4. Cast API `POST /play {"episode_id", "profile_ids"}` (1–20 ids; a 422 otherwise). In `state()`, each `timer.profiles[]` entry gains `remaining_s`, `can_start`, `reason` and `watching`, and `now_playing` gains `profile_ids`.

**Tests to add:** the timer and controller cases under "Tests" in the plan. They use the fake clock (`tests/timer/timer_helpers.py`, `conftest.py`) and the fake Chromecast.

## Subagent B: web backend, kid API and admin

**Files:** `tellybox/web/*.py`, `tellybox/web/admin/` (Python, templates, `admin/static/`), `tellybox/history.py`, `tellybox/library.py` (profile photo helpers only), `tellybox/locale/`, `tests/web/`, `tests/test_history.py`. Don't touch `tellybox/web/static/`.

**Contract to read:**
- migration `005_profiles.sql`;
- `tellybox/avatars.py`;
- `docs/kid-api.md` (the new endpoints and KidState fields);
- `docs/cast-api.md` (the cast state shape, which your fake cast client must produce).

**Tasks**
1. Kid API in `kid.py`:
   - `GET /api/kid/profiles`;
   - `?profiles=` on home and shows: a merged continue watching, group progress, and a 400 on bad ids;
   - `POST /api/kid/play` with `profile_ids`, returning 409 if any member is out of time;
   - the per-profile KidState fields (`profiles`, `watching`, `day`);
   - `GET /img/profile/{id}.jpg`.

   Remove `household_profile_id()` once nothing uses it. `cast_client.play(episode_id, profile_ids)`.
2. Admin `/admin/profiles`, plus a nav entry:
   - list, add, rename, reorder;
   - an avatar picker (radio tiles showing `/static/avatars/{key}.svg`, validated against `AVATARS`);
   - photo upload and remove through `tellybox/images.py`, under `media/profiles/`;
   - delete with a confirm, refused for the last profile and for a profile that is watching.
   - Every POST passes the existing Origin check, as the other admin forms do.
3. Settings: show the avatar next to each profile's fields. Dashboard: the avatar, a "watching" badge, and per-profile override buttons plus "everyone". History: names/avatars per row, and a `?profile=` filter.
4. i18n: mark every new string, add the admin JS strings to `js_strings.py`, run `scripts/i18n.sh`, and translate the new entries into nl and de, informally ("je", "du"). `tests/test_i18n.py` must pass.
5. Escape profile names everywhere, including the dashboard's live DOM updates.

**Tests to add:** the kid API and admin cases under "Tests" in the plan, with the existing fakes in `tests/web/conftest.py` and `tests/web/admin/conftest.py`.

## Subagent C: kid app frontend

**Files:** `tellybox/web/static/` (the JS, CSS, `i18n.js`, and a new `avatars/`), `scripts/kid_mock_server.py`. Nothing else.

**Contract to read:**
- `docs/kid-api.md` (the profiles endpoint, the `?profiles=` parameter, play with `profile_ids`, and the KidState `profiles`/`watching`/`day`);
- `tellybox/avatars.py` (the 8 keys: fox, bear, rabbit, owl, cat, dog, frog, penguin).

**Tasks**
1. Eight SVGs in `static/avatars/{key}.svg`: a flat, friendly animal head on a round sky-coloured disc, readable at 64 px, in the style of `icons.js` and `sky.js`, each under 3 KB.
2. The `#/who` who's-watching screen (PR-2):
   - big round pictures (the photo, else the avatar SVG, else a placeholder), with no visible text;
   - tapping toggles a selected ring and a check icon, and several can be selected;
   - a big "go" arrow button appears when at least one kid is selected;
   - profiles out of time are drawn at night (dimmed, with a moon) and can't be selected.
3. The selection lives in `localStorage` as `{profiles, day, last_used}`, with every access in try/catch. The picker shows when there is no selection, the `day` changed, more than 30 minutes passed since `last_used`, or a selected profile is gone.
4. An avatar button (the selected pictures, stacked) in the top corner of home and show pages goes to `#/who`.
5. Pass the group on home, shows and play. Reduce the sky and time-up from `state.profiles` for this device's group: the lowest fraction, `last_five` if any member has 5 minutes or less, and time up if any member is out of time.
6. The screen-reader labels ("Who's watching?", "Go", "Change who's watching", and each profile's name as its `aria-label`) go in `static/i18n.js`, in en, nl and de.
7. `scripts/kid_mock_server.py`: three profiles (one out of time), the picker, one kid watching, and two watching together.
8. Take screenshots of the picker (day, one out of time), home with the avatar button, and watching together, at 375×667, 768×1024 and 1440×900. Use Playwright against the mock server, and save them to your worktree's `screenshots/` folder, which is not committed. List their paths in your report.

**Checks:** the tap targets stay large (KA-1), and nothing depends on reading (KA-2). The existing kid tests (`tests/web/test_kid_*`) still pass.

## Controller checklist after the subagents

1. Merge A, B, C into `step8/profiles`, resolving conflicts. Run the full suite, `scripts/i18n.sh` and `tests/test_i18n.py`.
2. Review:
   - timer correctness against WT-1..9 and PR-4;
   - XSS in profile names;
   - photo path checks;
   - the delete guards;
   - the SSE state size with several profiles.
3. Review the screenshots with the owner (a private artifact page).
4. Deploy through CI after the merge, then do the real-device checks in the plan with the owner.
5. Update `docs/PROGRESS.md`, and the PRD status for v2.
