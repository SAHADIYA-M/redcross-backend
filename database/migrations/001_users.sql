-- ============================================================
-- RedCross Nexus — Migration 001: Users table
-- Adds application-layer authentication (separate from responders).
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('ADMIN','ASSESSOR','REVIEWER','RESPONDER','VIEWER')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower
    ON users (lower(username));
