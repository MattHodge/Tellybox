# Step 7: Playlists and episode titles (CI-7, KA-10)

Status: approved 2026-09-28 (200 cap, publish-all included).

## What already exists

- `source_video.publish = 'hold'` downloads a video but keeps its episode hidden; the library's "Held downloads" list publishes it (`library.publish_held`). CI-7's "held for approval" reuses this unchanged.
- `ingest.add(info, publish=…)` creates a `source_video` and one DOWNLOAD job. A playlist add calls the same path once per video, so it is one job per video for free.
- The kid API already sends `title` on every episode tile (currently a screen-reader label only). KA-10 is a frontend change.

## Part A: backend (yt-dlp, ingest, migration)

1. `ytdlp.py`
   - `classify_url(url) -> "video" | "playlist" | "both" | "channel"`. It is pure, with no network. `watch?v=X&list=Y` is `both`, except YouTube Mixes (`list=RD…`), which are auto-generated recommendations and count as `video`. `/playlist?list=` is `playlist`. `/@name`, `/channel/`, `/c/` and `/user/` are `channel`.
   - `preview_playlist(url) -> PlaylistInfo(id, title, channel_name, entries: list[PlaylistEntry])`, using `-J --flat-playlist`. A real 150-video playlist returns in one call, and every entry carries id, title, duration, channel_id, channel, thumbnails, availability and live_status.
   - `PlaylistEntry.unavailable_reason` is set for private or deleted entries (`[Private video]`/`[Deleted video]`, or `availability` not public/unlisted) and for live or upcoming ones.
   - Cap: at most 200 entries. Longer playlists show "the first 200", and the admin can add the rest later; already-added videos are skipped.
   - `parse_info` keeps rejecting playlists for the single-video path.
2. Migration `004_playlists.sql` adds `source_video.playlist_id` and `source_video.playlist_title`, both nullable. They are used only to group held videos in the library.
3. `ingest.add_playlist(conn, playlist, youtube_ids, *, publish, now) -> AddResult(added, skipped)`:
   - It runs as one transaction with one `source_video` and one DOWNLOAD job per selected entry.
   - Videos already in the library are skipped rather than raising an error.
   - Rows are built from the flat entry (title, duration, channel, thumbnail URL, a canonical `watch?v=<id>` URL).
4. Download job: a flat entry has no chapters, so `_publish` fills `chapters_json` (and channel, if it was missing) from the full info the download returns. Chapter import (ES-1, step 8) keeps working for playlist videos.
5. `library.publish_held_playlist(conn, playlist_id)` publishes every *ready* held video from that playlist. Videos that are still downloading stay held.

## Part B: admin add page and library

1. Add page (`add.py`, `add.html`):
   - Preview branches on `classify_url`:
     - `channel`: "Channel URLs are for subscriptions (coming in v2)."
     - `both`: two buttons, "Just this video" / "Whole playlist", which re-submit the preview with a mode.
   - The playlist preview shows the playlist title and count. Below that is a list of the videos with thumbnail, title, channel and duration, each with a checkbox. The checkboxes are ticked by default, and videos already added or unavailable are shown greyed out and unticked. Next come a "Hold for approval" checkbox (ticked by default) and an "Add N videos" button.
   - The preview is kept server-side as today; the form carries the preview id plus the selected ids, which are checked against the preview.
   - After adding, the page redirects to Jobs with "Added 23 videos (held), skipped 2".
   - The single-video form is unchanged ("Add" / "Add and hold").
2. Library "Held downloads": videos from the same playlist are grouped under the playlist title, with a "Publish all ready" button per group. Per-video publish stays.

## Part C: kid app titles (KA-10)

- `episodeTile` in `app.js` adds a caption under the thumbnail: small, two lines maximum (`line-clamp`), and `aria-hidden` because the `aria-label` already carries the title. It appears in the episode grid and in continue watching; show tiles are unchanged.
- The caption is styled for day, dusk and night (it stays readable when the tiles dim at night). Tile sizes are adjusted so the grids still fit on 4.7" phones.
- `docs/kid-api.md` is updated: `title` is now shown.
- Screenshots of every state at three sizes from `scripts/kid_mock_server.py`, reviewed as in step 4.

## Execution (at most 3 subagents)

1. I write the shared contract first: the dataclasses and function signatures for A, which B builds on.
2. Three parallel subagents, one per part (A, B, C). B codes against the contract with a fake `YtDlp`. C touches only static files.
3. I integrate, run the full suite, and review the diff (XSS in the playlist and video titles, preview-id tampering, and the transaction on add).

## Tests

- `classify_url` table; `parse_playlist` from recorded flat-playlist JSON fixtures, including private, deleted and upcoming entries.
- `add_playlist`: one job per selected video, skips, the hold flag, and a rollback on error.
- The download fills in chapters. Publish-all publishes only ready held videos of that playlist.
- Admin routes: preview branches, selection outside the preview is rejected, an expired preview, and the redirect message.
- No network in tests.

## Real-device checks (owner, on the home server)

1. Add a real kids' playlist with "hold" on. Check that the Jobs page shows one job per video, the kid app shows nothing new, and the library groups them. Then use "Publish all ready" and check they appear.
2. Paste a `watch?v=…&list=…` link and pick "Just this video".
3. On the phone, check that episode titles are visible and short enough, that a long one is cut off at two lines, and that titles are readable at night.

