-- Playlists (v1 step 7, CI-7): remember which playlist a video was added from,
-- so held videos can be grouped and published together in the library.
ALTER TABLE source_video ADD COLUMN playlist_id TEXT;
ALTER TABLE source_video ADD COLUMN playlist_title TEXT;
