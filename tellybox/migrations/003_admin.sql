-- Admin pages (v1 step 5): sign-in (AD-1, NF-2).

-- One row per signed-in browser. Only a SHA-256 of the cookie token is stored.
CREATE TABLE admin_session (
    token_hash   TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL      -- sliding 30-day expiry
);

-- Failed sign-ins per client address; each failure doubles the wait, 1 s up to 60 s.
CREATE TABLE login_throttle (
    address         TEXT PRIMARY KEY,
    failures        INTEGER NOT NULL DEFAULT 0,
    next_allowed_at TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

-- argon2id hash of TELLYBOX_ADMIN_PASSWORD, stored by the web service at startup.
ALTER TABLE settings ADD COLUMN admin_password_hash TEXT;
