"""
apply_users_table.py
--------------------
Creates the `users` table and its case-insensitive username index in the
Supabase database, then prints the resulting column structure so you can
confirm it looks correct.

Does NOT insert any rows or touch any other table.

Usage
-----
    python database/scripts/apply_users_table.py

Config
------
    DATABASE_URL must exist in the .env file at the project root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ------------------------------------------------------------------ #
# Load .env from project root (two levels above database/scripts/)   #
# ------------------------------------------------------------------ #
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    sys.exit("DATABASE_URL not found in .env — aborting.")

try:
    import psycopg
except ImportError:
    sys.exit("Missing dependency: psycopg\nInstall with: pip install 'psycopg[binary]'")

# ------------------------------------------------------------------ #
# SQL to create the table and index                                   #
# ------------------------------------------------------------------ #
_MIGRATION_SQL = """
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
"""

# ------------------------------------------------------------------ #
# Query to inspect the resulting column structure                     #
# ------------------------------------------------------------------ #
_INSPECT_SQL = """
SELECT
    column_name,
    data_type,
    character_maximum_length,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name   = 'users'
ORDER BY ordinal_position;
"""

_INSPECT_INDEXES_SQL = """
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename  = 'users'
ORDER BY indexname;
"""


def main() -> None:
    print("Connecting to database …")

    with psycopg.connect(_DATABASE_URL, prepare_threshold=None) as conn:
        # ---------------------------------------------------------- #
        # Apply migration                                             #
        # ---------------------------------------------------------- #
        print("Creating table and index (IF NOT EXISTS — safe to re-run) …")
        conn.execute(_MIGRATION_SQL)
        conn.commit()
        print("✓ Done.\n")

        # ---------------------------------------------------------- #
        # Show column structure                                       #
        # ---------------------------------------------------------- #
        print("=== Column structure of public.users ===")
        cols = conn.execute(_INSPECT_SQL).fetchall()
        if not cols:
            print("  (table not found — something went wrong)")
        else:
            header = f"{'Column':<20} {'Type':<25} {'Default':<30} {'Nullable'}"
            print(header)
            print("-" * len(header))
            for col_name, data_type, _, col_default, nullable in cols:
                print(
                    f"{col_name:<20} {data_type:<25} "
                    f"{str(col_default or ''):<30} {nullable}"
                )

        # ---------------------------------------------------------- #
        # Show indexes                                                #
        # ---------------------------------------------------------- #
        print("\n=== Indexes on public.users ===")
        idxs = conn.execute(_INSPECT_INDEXES_SQL).fetchall()
        for idx_name, idx_def in idxs:
            print(f"  {idx_name}")
            print(f"    {idx_def}")

        print("\nAll done — no rows were inserted, no other tables were touched.")


if __name__ == "__main__":
    main()
