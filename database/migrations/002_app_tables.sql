-- ============================================================
-- RedCross Nexus — Migration 002: Phase 15 application tables
--
-- Adds the application-layer persistence tables (SQLAlchemy /
-- PostgreSQL) required by the Phase 15 storage integration.
--
-- GUARANTEES:
--   * ADDITIVE only — never drops, truncates or alters existing
--     tables, schemas or data.
--   * IDEMPOTENT — every statement uses IF NOT EXISTS so it can be
--     re-run safely against an already-migrated database.
--   * Does NOT create or alter the `users` table (created by 001).
--
-- Table names deliberately avoid collisions with the older team
-- schema (database/schema_v2.sql):
--   * verification records live in `verification_records`, NOT `verifications`;
--   * per-report structured needs live in `report_need_records`, NOT
--     `report_needs` (the team's schema_v2.sql already owns `report_needs`
--     with a DIFFERENT shape: need_id FK / priority_id / confidence — no
--     `need` text column). Reusing that name would silently no-op this
--     CREATE TABLE (IF NOT EXISTS) and then fail building indexes on the
--     nonexistent `need` column. Index names are also renamed so they do
--     not collide with the team's `idx_report_needs_*` entries.
-- ============================================================

-- ------------------------------------------------
-- Reports (maps the app-domain humanitarian report)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    report_id             TEXT PRIMARY KEY,
    original_text         TEXT NOT NULL,              -- immutable evidence
    reporter              TEXT NOT NULL,
    timestamp             TIMESTAMPTZ NOT NULL,       -- event time
    location              TEXT,
    incident              TEXT,
    evidence              JSONB NOT NULL DEFAULT '[]',
    status                TEXT NOT NULL DEFAULT 'RECEIVED',
    source                TEXT,
    location_status       TEXT,                       -- CONFIRMED / UNCERTAIN
    severity              TEXT,
    affected_population   INTEGER,
    infrastructure_status TEXT,
    available_needs       JSONB NOT NULL DEFAULT '[]',
    vulnerability         JSONB NOT NULL DEFAULT '[]',
    time_sensitivity      TEXT,
    verification_status   TEXT NOT NULL DEFAULT 'UNVERIFIED',
    original_extraction   JSONB NOT NULL DEFAULT '{}', -- immutable AI snapshot
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reports_status
    ON reports (status);
CREATE INDEX IF NOT EXISTS idx_reports_verification_status
    ON reports (verification_status);
CREATE INDEX IF NOT EXISTS idx_reports_timestamp
    ON reports (timestamp);
CREATE INDEX IF NOT EXISTS idx_reports_source
    ON reports (source);
CREATE INDEX IF NOT EXISTS idx_reports_location_status
    ON reports (location_status);

-- ------------------------------------------------
-- Report needs (normalized one-row-per-need)
-- NOTE: named `report_need_records` (NOT `report_needs`) — see header —
-- because the team's schema_v2.sql already owns a differently-shaped
-- `report_needs` table. This table further avoids the team's index names.
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS report_need_records (
    id        BIGSERIAL PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES reports (report_id) ON DELETE CASCADE,
    need      TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_report_need_records_report_need
    ON report_need_records (report_id, need);
CREATE INDEX IF NOT EXISTS idx_report_need_records_need
    ON report_need_records (need);
CREATE INDEX IF NOT EXISTS idx_report_need_records_report
    ON report_need_records (report_id);

-- ------------------------------------------------
-- Verification records (append-only; avoids the
-- team's `verifications` table name in schema_v2.sql)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS verification_records (
    verification_id TEXT PRIMARY KEY,
    report_id       TEXT NOT NULL REFERENCES reports (report_id) ON DELETE CASCADE,
    action          TEXT NOT NULL,
    previous_status TEXT,
    new_status      TEXT,
    reviewer_id     TEXT,
    reason          TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    changes         JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_verification_records_report
    ON verification_records (report_id);
CREATE INDEX IF NOT EXISTS idx_verification_records_timestamp
    ON verification_records (timestamp);

-- ------------------------------------------------
-- Audit log (append-only)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id  TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES reports (report_id) ON DELETE CASCADE,
    action    TEXT NOT NULL,
    actor_id  TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason    TEXT,
    old_value JSONB NOT NULL DEFAULT '{}',
    new_value JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_report
    ON audit_logs (report_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp
    ON audit_logs (timestamp);

-- ------------------------------------------------
-- Response activities (Phase 12 coverage)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS response_activities (
    response_id         TEXT PRIMARY KEY,
    report_id           TEXT NOT NULL REFERENCES reports (report_id) ON DELETE CASCADE,
    need                TEXT,
    activity            TEXT NOT NULL,
    response_status     TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    location            TEXT,
    source              TEXT,
    notes               TEXT,
    affected_population INTEGER
);

CREATE INDEX IF NOT EXISTS idx_response_activities_report
    ON response_activities (report_id);
CREATE INDEX IF NOT EXISTS idx_response_activities_status
    ON response_activities (response_status);
CREATE INDEX IF NOT EXISTS idx_response_activities_timestamp
    ON response_activities (timestamp);

-- ------------------------------------------------
-- Fusion candidates (duplicate / conflict review)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS fusion_candidates (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,             -- POSSIBLE_DUPLICATE / POSSIBLE_CONFLICT
    report_ids  JSONB NOT NULL DEFAULT '[]',
    cluster_id  TEXT NOT NULL,
    reason      TEXT NOT NULL,
    similarity  DOUBLE PRECISION,
    status      TEXT NOT NULL DEFAULT 'PENDING',
    resolution  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_fusion_candidates_status
    ON fusion_candidates (status);
CREATE INDEX IF NOT EXISTS idx_fusion_candidates_type
    ON fusion_candidates (type);

-- ------------------------------------------------
-- Priority results (backend-computed only)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS priority_results (
    report_id                   TEXT PRIMARY KEY REFERENCES reports (report_id) ON DELETE CASCADE,
    severity_score              DOUBLE PRECISION NOT NULL,
    affected_population_score   DOUBLE PRECISION NOT NULL,
    vulnerability_score         DOUBLE PRECISION NOT NULL,
    time_sensitivity_score      DOUBLE PRECISION NOT NULL,
    evidence_verification_score DOUBLE PRECISION NOT NULL,
    final_score                 DOUBLE PRECISION NOT NULL,
    priority_level              TEXT NOT NULL,        -- CRITICAL / HIGH / MEDIUM / LOW
    calculation_version         TEXT NOT NULL,
    calculated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);