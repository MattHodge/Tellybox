# Casting spike: findings (v1 build step 1)

_2026-09-27 · run from a Docker container (`network_mode: host`) on the Fedora dev machine, same LAN as the Chromecast._

**Device:** "Living Room TV", original 1st-gen Chromecast (`model: Chromecast`).
**Media:** `spike/make_test_clip.sh`, a 2-minute clip, 1280×720 H.264 Main@4.0 yuv420p, AAC stereo, faststart.
**Library:** pychromecast 14.0.10, Python 3.12 (container).

**Verdict:** casting our own MP4 to the Default Media Receiver works on the 1st-gen Chromecast from a host-networked container. The two biggest risks in the PRD ("mDNS fails inside Docker" and "ageing Chromecast") are retired.

## Checklist results

| # | Check | Result | Notes |
|---|---|---|---|
| 1 | Discovery from the container | ✅ | Found in ~6 s (the full discovery timeout). |
| 2 | Cast clip, measure tap-to-playing (NF-5) | ✅ | **4.26 s / 3.83 s** cold (from Backdrop); **0.86 s** when the Default Media Receiver was already running. |
| 3 | Pause and resume from our code | ✅ | PAUSED and PLAYING events arrive within ~1 s. |
| 4 | Pause and resume from the Google Home app | ✅ | External pause and resume reach our media listener as normal status events. |
| 5 | Clip ends | ✅ | `IDLE` + `idle_reason=FINISHED`. The receiver app stays loaded. |
| 6 | Seek | ✅ | `seek 60`: BUFFERING ~3 s, then PLAYING at 60.33. The Chromecast uses Range requests (206). |
| 7 | Foreign cast mid-play (YouTube from a phone) | ✅ | Receiver `session_id` → null about 4 s before YouTube's app starts, which we detect. Afterwards the Chromecast returns to Backdrop by itself. |
| 8 | Power loss mid-play | ✅ | `LOST` immediately. pychromecast retries with backoff and reconnects on its own (~39 s after LOST, including boot). After reboot the device is on Backdrop; our session is gone. |
| 9 | Restart our process while playing | ✅ | A fresh process sees the Default Media Receiver session, our `content_id` URL, `PLAYING` and the position. We can re-attach. |

## Findings that shape step 2 (cast controller and timer)

1. **No periodic status while playing.** The Chromecast only pushes media status on state changes (play, pause, buffering, seek, idle), not every second. The timer must account play time from state transitions with its own clock (`adjusted_current_time`-style), and poll `update_status()` occasionally (e.g. every 15–30 s) as a drift check and a persist tick (WT-8).
2. **Position is 0 on FINISHED.** `current_time` is 0 in the `IDLE/FINISHED` status. PB-4 must use the last known position before idle (or duration) to mark an episode finished.
3. **BUFFERING flaps around PLAYING.** At start and after a seek there are 1–3 BUFFERING events. In "ignore pauses" mode, decide whether buffering counts. Suggestion: count it (it's short and not the kid's fault), and never count PAUSED.
4. **The media listener follows any app.** After YouTube took over, pychromecast kept delivering YouTube's media status (`content_id` is a YouTube ID) to our listener. The controller must filter on *our* receiver `session_id` and our `content_id` before counting time or reacting (WT-9).
5. **Classify the end of a session by cause (PB-5).** The spike labels any `session_id` change as `FOREIGN_TAKEOVER`, including the Backdrop after a reboot. Step 2 should record "session ended" with a reason: finished, stopped by us, taken over (new app_id ≠ Default Media Receiver or new content), or connection lost.
6. **Cold start is close to the 5 s target (NF-5).** Launching the Default Media Receiver costs ~3 s. Options: keep the receiver loaded between episodes (autoplay does this naturally), or launch it when a kid page is opened. Worth measuring again on the server over wired Ethernet.
7. **Restart recovery (NF-7) is feasible.** Identify our session after a restart by matching the `content_id` against our media URL scheme. This means media URLs must stay valid across restarts: signed, expiring tokens (NF-3) rather than a per-process random prefix like in this spike.
8. **The Chromecast buffers ahead.** Playback continued after our media server stopped. Stopping playback must be an explicit `stop`/`quit_app`, never "stop serving the file".
9. **Discovery takes a fixed ~6 s** with the default timeout. Cache the device's UUID and host (PB-1 "remembers it"). Connect with `known_hosts` and fall back to full discovery.

## Environment notes

- **Fedora SELinux:** bind mounts need `:z` (`./media:/media:ro,z`). Harmless on Ubuntu.
- **Fedora firewalld** (`FedoraWorkstation` zone) already allows TCP/UDP 1025–65535, so port 8765 needed no change. Check the Ubuntu server's `ufw` in step 7.
- **`docker compose` plugin** is not installed on the dev machine; the spike ran with `docker run --network host`. Install with `sudo dnf install docker-compose-plugin`.

## How to reproduce

```bash
spike/make_test_clip.sh                     # -> media/test_clip.mp4 (verifies format)
docker build -t tellybox-spike .
docker run --rm --network host tellybox-spike discover
docker run --rm -it --network host -v "$PWD/media:/media:ro,z" \
  tellybox-spike play /media/test_clip.mp4 --name "Living Room TV"
# p / r / s / seek N / replay / q (stop and quit) / x (quit, leave playing)
```
