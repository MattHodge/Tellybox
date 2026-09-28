-- Ingest pipeline (v1 step 3): source videos, background jobs, tool versions.

-- The downloaded original (PRD data model "SourceVideo"). May be deleted after splitting (step 6).
CREATE TABLE source_video (
    id             INTEGER PRIMARY KEY,
    youtube_id     TEXT    NOT NULL UNIQUE,
    url            TEXT    NOT NULL,
    title          TEXT    NOT NULL,
    channel_id     TEXT,
    channel_name   TEXT,
    duration_s     REAL,
    chapters_json  TEXT,               -- [{"start_s", "end_s", "title"}], for chapter import (ES-1, step 6)
    thumbnail_url  TEXT,
    thumbnail_path TEXT,               -- relative to the media dir
    file_path      TEXT,               -- relative to the media dir; NULL until published
    show_id        INTEGER REFERENCES show(id) ON DELETE SET NULL,
    publish        TEXT    NOT NULL DEFAULT 'publish' CHECK (publish IN ('publish', 'hold')),
    status         TEXT    NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued', 'downloading', 'processing', 'ready', 'failed')),
    error          TEXT,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL
);

-- Background jobs run by the worker service (CI-3, NF-7).
CREATE TABLE job (
    id           INTEGER PRIMARY KEY,
    type         TEXT    NOT NULL CHECK (type IN ('download', 'update_ytdlp')),
    target_id    INTEGER,          -- source_video.id for download jobs
    status       TEXT    NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'downloading', 'processing', 'ready', 'failed')),
    progress     REAL,             -- 0..1 within the current status
    error        TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 4,
    run_after    TEXT    NOT NULL,
    heartbeat_at TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    finished_at  TEXT
);
CREATE INDEX job_queue ON job (status, run_after, id);

-- Installed versions of updatable tools (CI-5), shown on the admin dashboard.
CREATE TABLE tool_version (
    name       TEXT PRIMARY KEY,   -- 'yt-dlp'
    version    TEXT NOT NULL,
    path       TEXT,
    checked_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Episodes come from a source video, optionally a segment of it (splitting, step 6).
ALTER TABLE episode ADD COLUMN source_video_id INTEGER REFERENCES source_video(id) ON DELETE SET NULL;
ALTER TABLE episode ADD COLUMN start_s REAL;
ALTER TABLE episode ADD COLUMN end_s REAL;

CREATE INDEX show_channel ON show (youtube_channel_id);
