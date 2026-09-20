-- ============================================================
-- RedCross Nexus — Query: Login lookup
-- Finds a user by username, case-insensitively.
-- Parameter: %(username)s  (psycopg3 / asyncpg style)
--
-- Returns: user_id, username, password_hash, role, is_active
-- The caller must:
--   1. Check is_active == True before accepting the login.
--   2. Verify the supplied password against password_hash using
--      a constant-time comparison (e.g. bcrypt.checkpw).
-- ============================================================

SELECT
    user_id,
    username,
    password_hash,
    role,
    is_active
FROM users
WHERE lower(username) = lower(%(username)s);
