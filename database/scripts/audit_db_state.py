"""
audit_db_state.py
-----------------
READ-ONLY audit of the live Supabase database.
Reports which tables exist, row counts, and embedding status.
Touches nothing. Safe to run at any time.
Results are written to database/scripts/audit_result.txt (UTF-8).

Usage
-----
    python database/scripts/audit_db_state.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    sys.exit("DATABASE_URL not found in .env — aborting.")

try:
    import psycopg
except ImportError:
    sys.exit("Missing psycopg. Run: pip install 'psycopg[binary]'")

# All tables that should exist after schema_v2.sql + migration 001
EXPECTED_TABLES = [
    # Lookup tables
    "needs",
    "priority",
    # Core entities
    "responders",
    "locations",
    "field_reports",
    "report_needs",
    "affected_people",
    "evidence",
    # Fusion layer
    "report_clusters",
    "cluster_members",
    "verifications",
    # Auth (migration 001)
    "users",
]


def main() -> None:
    print("Connecting …\n")

    with psycopg.connect(_DATABASE_URL, prepare_threshold=None) as conn:

        # ── 1. Which expected tables actually exist? ─────────────────────
        existing = {
            row[0]
            for row in conn.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            ).fetchall()
        }

        print("=== Table existence (schema_v2 + migration 001) ===")
        all_present = True
        for tbl in EXPECTED_TABLES:
            status = "[OK] exists" if tbl in existing else "[!!] MISSING"
            if tbl not in existing:
                all_present = False
            print(f"  {tbl:<25} {status}")

        print()
        if all_present:
            print("  All expected tables are present.\n")
        else:
            print("  WARNING: Some tables are missing -- schema_v2.sql may not have been applied.\n")

        # ── 2. Row counts for tables that exist ──────────────────────────
        print("=== Row counts ===")
        for tbl in EXPECTED_TABLES:
            if tbl not in existing:
                print(f"  {tbl:<25} (skipped — table missing)")
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl:<25} {count:>5} row(s)")

        # ── 3. Embedding status in field_reports ─────────────────────────
        if "field_reports" in existing:
            print()
            print("=== field_reports embedding status ===")
            total, with_emb, without_emb = conn.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(embedding),
                    COUNT(*) FILTER (WHERE embedding IS NULL)
                FROM field_reports
                """
            ).fetchone()
            print(f"  Total reports     : {total}")
            print(f"  With embedding    : {with_emb}")
            print(f"  Missing embedding : {without_emb}")
            if without_emb > 0:
                print("  ACTION NEEDED: Run embed_reports.py to fill missing embeddings.")
            else:
                print("  All reports have embeddings.")

        # ── 4. users table indexes ────────────────────────────────────────
        if "users" in existing:
            print()
            print("=== users table indexes ===")
            idxs = conn.execute(
                """
                SELECT indexname, indexdef FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'users'
                ORDER BY indexname
                """
            ).fetchall()
            for name, defn in idxs:
                print(f"  {name}")
                print(f"    {defn}")

    print("\nAudit complete — nothing was modified.")


if __name__ == "__main__":
    main()
