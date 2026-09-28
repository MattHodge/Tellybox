-- Initial schema (v1 step 2). Timestamps are ISO-8601 UTC text; days are local dates (YYYY-MM-DD)
-- relative to the daily reset time (WT-1).

-- Profiles exist from v1 (single household profile) so v2 needs no history migration.
CREATE TABLE profile (
    id                  INTEGER PRIMARY KEY,
    name                TEXT    NOT NULL,
    picture_path        TEXT,
    daily_allowance_min INTEGER NOT NULL DEFAULT 60,
    counting_mode       TEXT    NOT NULL DEFAULT 'ignore_pauses'
                        CHECK (counting_mode IN ('ignore_pauses', 'wall_clock')),   -- WT-2
    max_session_min     INTEGER NOT NULL DEFAULT 90,                                -- WT-3
    created_at          TEXT    NOT NULL
);

-- Global settings, single row (AD-2).
CREATE TABLE settings (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    reset_time        TEXT    NOT NULL DEFAULT '04:00',   -- WT-1, local time HH:MM
    grace_cap_min     INTEGER NOT NULL DEFAULT 15,        -- WT-5
    session_break_min INTEGER NOT NULL DEFAULT 15         -- WT-3: this long without playing ends a viewing session
);

CREATE TABLE show (
    id                 INTEGER PRIMARY KEY,
    name               TEXT    NOT NULL,
    artwork_path       TEXT,
    autoplay           INTEGER NOT NULL DEFAULT 1,  -- LM-4, PB-3
    sort_order         INTEGER NOT NULL DEFAULT 0,
    hidden             INTEGER NOT NULL DEFAULT 0,  -- LM-3
    youtube_channel_id TEXT,
    created_at         TEXT    NOT NULL
);

-- Columns needed by step 2; the ingest pipeline (step 3) adds source video, offsets, etc.
CREATE TABLE episode (
    id             INTEGER PRIMARY KEY,
    show_id        INTEGER NOT NULL REFERENCES show(id) ON DELETE CASCADE,
    title          TEXT    NOT NULL,
    file_path      TEXT    NOT NULL,   -- relative to the media dir
    duration_s     REAL,
    thumbnail_path TEXT,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    hidden         INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);
CREATE INDEX episode_show_order ON episode (show_id, sort_order, id);

-- Known Chromecasts; the selected one is used (PB-1).
CREATE TABLE cast_device (
    uuid         TEXT PRIMARY KEY,
    name         TEXT,
    host         TEXT NOT NULL,
    port         INTEGER NOT NULL DEFAULT 8009,
    model        TEXT,
    selected     INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT
);

-- Timer state per profile per day (WT-1, WT-7, WT-8).
CREATE TABLE daily_usage (
    profile_id   INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    day          TEXT    NOT NULL,
    seconds_used REAL    NOT NULL DEFAULT 0,
    extra_min    INTEGER NOT NULL DEFAULT 0,
    unlimited    INTEGER NOT NULL DEFAULT 0,
    blocked      INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT,
    PRIMARY KEY (profile_id, day)
);

-- One row per episode played (history, AD-4). Purged after 21 days (AD-5, step 5).
CREATE TABLE watch_session (
    id                INTEGER PRIMARY KEY,
    episode_id        INTEGER REFERENCES episode(id) ON DELETE SET NULL,
    started_at        TEXT    NOT NULL,
    ended_at          TEXT,
    seconds_counted   REAL    NOT NULL DEFAULT 0,
    end_reason        TEXT,     -- finished | replaced | stopped | time_up | blocked | taken_over | disconnected | restart
    last_heartbeat_at TEXT,     -- last persist tick; used to close sessions after a crash (NF-7)
    cast_session_id   TEXT      -- receiver session id, to recognise our session (WT-9)
);
CREATE INDEX watch_session_open ON watch_session (ended_at);

CREATE TABLE watch_session_profile (
    watch_session_id INTEGER NOT NULL REFERENCES watch_session(id) ON DELETE CASCADE,
    profile_id       INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    PRIMARY KEY (watch_session_id, profile_id)
);

-- Continue watching (PB-4).
CREATE TABLE playback_position (
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    episode_id INTEGER NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
    position_s REAL    NOT NULL DEFAULT 0,
    finished   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (profile_id, episode_id)
);

-- Parent overrides applied (WT-7, AD-4).
CREATE TABLE override_log (
    id         INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profile(id) ON DELETE CASCADE,
    day        TEXT    NOT NULL,
    kind       TEXT    NOT NULL,   -- extra_minutes | unlimited | block | stop_now
    value      INTEGER,
    created_at TEXT    NOT NULL
);

-- Watch timer state that must survive restarts (WT-8): the current viewing session (WT-3)
-- and any pending time-up. Single row.
CREATE TABLE timer_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    state_json       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

INSERT INTO settings (id) VALUES (1);
INSERT INTO profile (name, created_at) VALUES ('Household', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
