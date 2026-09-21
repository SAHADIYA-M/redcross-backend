"""
apply_schema.py
---------------
Applies the Phase 15 application tables to the PostgreSQL/Supabase database by
executing database/migrations/002_app_tables.sql.

The migration is ADDITIVE and IDEMPOTENT (every statement is IF NOT EXISTS), so
re-running it is safe. It never drops or alters existing team tables.

Usage
-----
    python database/scripts/apply_schema.py

Config
------
    DATABASE_URL must exist in the .env file at the project root.
    Credentials are loaded from the environment and never printed or logged.
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
    sys.exit(
        "DATABASE_URL not found in .env — aborting. "
        "Add the connection string to .env (never commit it)."
    )

try:
    import psycopg
except ImportError:
    sys.exit("Missing dependency: psycopg\nInstall with: pip install 'psycopg[binary]'")

_MIGRATION_SQL_PATH = Path(__file__).resolve().parents[1] / "migrations" / "002_app_tables.sql"


def main() -> None:
    if not _MIGRATION_SQL_PATH.exists():
        sys.exit(f"Migration file not found: {_MIGRATION_SQL_PATH}")

    migration_sql = _MIGRATION_SQL_PATH.read_text(encoding="utf-8")

    print("Connecting to database …")
    with psycopg.connect(_DATABASE_URL, prepare_threshold=None) as conn:
        conn.execute(migration_sql)
        conn.commit()

    # Inspect the affected tables so the result is visible without revealing
    # anything about the connection (no URL, no credentials, no data).
    inspect_sql = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
          'reports',
          'report_need_records',
          'verification_records',
          'audit_logs',
          'response_activities',
          'fusion_candidates',
          'priority_results'
      )
    ORDER BY table_name;
    """
    with psycopg.connect(_DATABASE_URL, prepare_threshold=None) as conn:
        tables = [row[0] for row in conn.execute(inspect_sql).fetchall()]

    print(f"Phase 15 tables present ({len(tables)}):")
    for name in tables:
        print(f"  - {name}")

    print("\nDone — additive migration applied. Existing tables and data were not touched.")


if __name__ == "__main__":
    main()