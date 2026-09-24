-- ============================================================
-- RedCross Nexus — PostgreSQL Schema (v2)
-- Humanitarian AI Evidence-Fusion Layer
-- CHANGE FROM v1: field_reports can now have MULTIPLE needs
-- (via the new report_needs table), instead of exactly one.
-- ============================================================
-- Run this on a fresh database:
--   psql "your_connection_string" -f schema_v2.sql
-- ============================================================

-- ---------- EXTENSIONS ----------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector, for embeddings

-- ============================================================
-- 1. LOOKUP TABLES
-- ============================================================

CREATE TABLE needs (
    need_id       SMALLSERIAL PRIMARY KEY,
    code          TEXT UNIQUE NOT NULL,   -- 'water','food','shelter','medical','sanitation','protection','infrastructure'
    label         TEXT NOT NULL,
    description   TEXT
);

CREATE TABLE priority (
    priority_id   SMALLSERIAL PRIMARY KEY,
    code          TEXT UNIQUE NOT NULL,   -- 'critical','high','medium','low'
    rank          SMALLINT NOT NULL,
    description   TEXT
);

-- ============================================================
-- 2. CORE ENTITIES
-- ============================================================

CREATE TABLE responders (
    responder_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name     TEXT NOT NULL,
    email         TEXT UNIQUE,
    phone         TEXT,
    organization  TEXT,
    role          TEXT NOT NULL DEFAULT 'field_reporter'
                  CHECK (role IN ('field_reporter','verifier','coordinator','admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE locations (
    location_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              TEXT NOT NULL,
    location_type     TEXT CHECK (location_type IN
                        ('school','relief_center','village','hospital','road','landmark','other')),
    raw_location_text TEXT,
    latitude          NUMERIC(9,6),
    longitude         NUMERIC(9,6),
    parent_location_id UUID REFERENCES locations(location_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Raw incoming observations: text reports, image captions, CSV/JSON rows.
-- CHANGED: need_id, priority_id, affected_population_estimate REMOVED from
-- here — a report can now describe several needs at once, so those fields
-- moved to report_needs below. This table is now purely about the
-- observation itself: who/where/when/what was said.
CREATE TABLE field_reports (
    report_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type           TEXT NOT NULL CHECK (source_type IN ('text','image','csv','json')),
    raw_content            TEXT NOT NULL,               -- original report/caption, immutable
    reporter_id            UUID REFERENCES responders(responder_id),
    location_id            UUID REFERENCES locations(location_id),
    reported_at             TIMESTAMPTZ NOT NULL,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding               vector(768),                 -- Gemini gemini-embedding-001,
                                                            -- output_dimensionality=768
    extraction_confidence   NUMERIC(4,3),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- NEW TABLE: one row per need mentioned in a report. A single report can
-- now have multiple rows here — e.g. "20 families need water, 5 houses
-- damaged, 3 people need medical attention" becomes 3 rows, one per need.
CREATE TABLE report_needs (
    report_need_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id         UUID NOT NULL REFERENCES field_reports(report_id) ON DELETE CASCADE,
    need_id           SMALLINT NOT NULL REFERENCES needs(need_id),
    priority_id        SMALLINT REFERENCES priority(priority_id),
    affected_population_estimate INTEGER,
    confidence          NUMERIC(4,3),                    -- LLM's confidence this need was
                                                            -- correctly identified, 0-1
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (report_id, need_id)                           -- a report can't list the same need twice
);

-- CHANGED: now points to report_needs instead of field_reports directly,
-- since population detail is really about ONE specific need within a
-- report, not the report as a whole.
CREATE TABLE affected_people (
    affected_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_need_id  UUID NOT NULL REFERENCES report_needs(report_need_id) ON DELETE CASCADE,
    count_estimate  INTEGER NOT NULL,
    unit            TEXT NOT NULL DEFAULT 'people' CHECK (unit IN ('people','families','households')),
    demographic_note TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- UNCHANGED: photos/files are about the whole report, not a specific need.
CREATE TABLE evidence (
    evidence_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id       UUID NOT NULL REFERENCES field_reports(report_id) ON DELETE CASCADE,
    evidence_type   TEXT NOT NULL CHECK (evidence_type IN ('photo','document','csv_row','json_blob','link')),
    file_url        TEXT,
    content         TEXT,
    caption         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 3. EVIDENCE-FUSION LAYER
-- ============================================================

CREATE TABLE report_clusters (
    cluster_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    need_id          SMALLINT REFERENCES needs(need_id),
    location_id      UUID REFERENCES locations(location_id),
    priority_id      SMALLINT REFERENCES priority(priority_id),
    estimated_affected INTEGER,
    status           TEXT NOT NULL DEFAULT 'needs_review'
                      CHECK (status IN ('needs_review','confirmed','edited','split','rejected')),
    ai_summary       TEXT,
    first_reported_at TIMESTAMPTZ NOT NULL,
    latest_update_at  TIMESTAMPTZ NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- CHANGED: now links a cluster to a specific report_need_id, not a whole
-- report. This is the key fix — it means one multi-need report can feed
-- several different clusters (one per need), each with its own
-- relationship type and score.
CREATE TABLE cluster_members (
    cluster_member_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id        UUID NOT NULL REFERENCES report_clusters(cluster_id) ON DELETE CASCADE,
    report_need_id    UUID NOT NULL REFERENCES report_needs(report_need_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL CHECK (relationship_type IN
                        ('supporting','potential_duplicate','conflicting','unrelated')),
    relationship_score NUMERIC(4,3),
    llm_explanation     TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, report_need_id)
);

CREATE TABLE verifications (
    verification_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id         UUID NOT NULL REFERENCES report_clusters(cluster_id) ON DELETE CASCADE,
    responder_id        UUID NOT NULL REFERENCES responders(responder_id),
    action              TEXT NOT NULL CHECK (action IN ('confirm','edit','split','reject')),
    notes               TEXT,
    previous_state       JSONB,
    new_state             JSONB,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 4. INDEXES
-- ============================================================

CREATE INDEX idx_field_reports_location    ON field_reports(location_id);
CREATE INDEX idx_field_reports_reported_at ON field_reports(reported_at);
CREATE INDEX idx_field_reports_embedding
    ON field_reports USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- report_needs: the hot table for "what needs exist, filtered by type"
CREATE INDEX idx_report_needs_report   ON report_needs(report_id);
CREATE INDEX idx_report_needs_need     ON report_needs(need_id);

CREATE INDEX idx_clusters_status    ON report_clusters(status);
CREATE INDEX idx_clusters_location  ON report_clusters(location_id);
CREATE INDEX idx_clusters_need      ON report_clusters(need_id);
CREATE INDEX idx_clusters_updated   ON report_clusters(latest_update_at DESC);

CREATE INDEX idx_cluster_members_cluster     ON cluster_members(cluster_id);
CREATE INDEX idx_cluster_members_report_need ON cluster_members(report_need_id);

CREATE INDEX idx_evidence_report         ON evidence(report_id);
CREATE INDEX idx_affected_people_need    ON affected_people(report_need_id);

CREATE INDEX idx_verifications_cluster ON verifications(cluster_id);

-- ============================================================
-- 5. SEED LOOKUP DATA
-- ============================================================

INSERT INTO needs (code, label) VALUES
    ('water', 'Drinking Water'),
    ('food', 'Food'),
    ('shelter', 'Shelter'),
    ('medical', 'Medical'),
    ('sanitation', 'Sanitation'),
    ('protection', 'Protection'),
    ('infrastructure', 'Infrastructure');

INSERT INTO priority (code, rank, description) VALUES
    ('critical', 1, 'Immediate life-threatening risk'),
    ('high', 2, 'Urgent, needs response within hours'),
    ('medium', 3, 'Needs response within 1-2 days'),
    ('low', 4, 'Monitor, no immediate danger');

-- ============================================================
-- 6. HELPER TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_clusters_touch
BEFORE UPDATE ON report_clusters
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
