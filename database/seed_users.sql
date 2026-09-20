-- ============================================================
-- RedCross Nexus — Seed: Users (non-login / inactive)
-- These three accounts exist as identity references only.
-- They cannot log in: is_active = FALSE, password_hash = ''.
-- Run AFTER migration 001_users.sql.
-- ============================================================

INSERT INTO users (user_id, username, password_hash, full_name, role, is_active) VALUES
    ('11111111111111111111111111111111', 'anju.menon',  '', 'Anju Menon', 'ASSESSOR', FALSE),
    ('22222222222222222222222222222222', 'ravi.kumar',  '', 'Ravi Kumar', 'ASSESSOR', FALSE),
    ('33333333333333333333333333333333', 'fathima.s',   '', 'Fathima S.', 'REVIEWER', FALSE)
ON CONFLICT (user_id) DO NOTHING;
