# Step 8: real-device checks (still to do)

Status: open. Kid profiles (PR #1) are deployed. These checks need the Living Room TV and two devices. Tick them off as you go, and note anything that looks wrong.

## Done (2026-09-29)

- [x] Admin: the household profile renamed to kid A, with an avatar, and kid B added with an avatar. Kid A kept today's usage from the household profile.
- [x] The Profiles, Dashboard, Settings and History pages look right in the browser.
- [x] The kid app's screens (picker and corner button) work.

## To do

The admin dashboard shows each kid's time used. The kid app's `/api/kid/state` shows `watching` and each kid's `fraction_left`, which is a quick way to confirm steps 1–4.

1. **One kid (PR-2, PR-3).** On the phone, pick kid A and play an episode.
   - [ ] Only kid A's time goes up; kid B's stays the same.
   - [ ] The dashboard shows the "watching" badge on kid A.
2. **Switching kids (A-5).** On a second device, pick kid B and play a different episode.
   - [ ] It replaces kid A's episode on the TV.
   - [ ] From then on only kid B's time goes up.
   - [ ] History shows kid A's episode as "replaced" and kid B's as a new row.
3. **Watching together (PR-4).** Pick both kids and play.
   - [ ] Both kids' time goes up.
   - [ ] Lower kid A's allowance in Settings until about a minute is left. The episode finishes (grace) and the TV stops; there's no autoplay.
   - [ ] The picker shows kid A at night. Kid B alone can still start an episode.
   - [ ] Put kid A's allowance back afterwards.
4. **Block (WT-7).** While kid A watches alone, block kid B on the dashboard.
   - [ ] Kid A's playback carries on.
   - [ ] Kid B's picture is at night on the picker and can't be picked.
   - [ ] Unblock kid B.
5. **Session limit per kid (A-13).** Optional, since it takes long: lower kid A's max session in Settings to a few minutes and let kid A watch past it.
   - [ ] Kid A's episode finishes and stops.
   - [ ] Kid B can start right away.
6. **Remembered pick (A-12).**
   - [ ] Leave a device unused for more than 30 minutes, then open it: it asks who's watching again.
   - [ ] The next morning (after 04:00), the device asks again.
7. **Photo (PR-1).** Upload a photo for one kid.
   - [ ] It replaces the avatar on the picker and in the corner button.
   - [ ] Removing the photo brings the avatar back.
8. **Restart during playback (WT-8).** Optional: restart the cast container while two kids are watching.
   - [ ] Playback is picked up again with the same two kids, and time keeps counting for both.

When all of these pass, mark v2 as done in `docs/PROGRESS.md` and the PRD release plan.
