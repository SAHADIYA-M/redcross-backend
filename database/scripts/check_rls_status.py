"""
check_rls_status.py
-------------------
READ-ONLY: checks the RLS (Row Level Security) status of every
table in the public schema. Touches nothing.

Usage:  .venv/Scripts/python.exe database/scripts/check_rls_status.py
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env", override=False)
DB_URL = os.environ.get("DATABASE_URL", "")
if not DB_URL:
    sys.exit("DATABASE_URL not in .env")

import psycopg

OUT = Path(__file__).parent / "rls_status.txt"
lines = []
log = lines.append

with psycopg.connect(DB_URL, prepare_threshold=None) as conn:
    # Which role does this connection see itself as?
    current_role = conn.execute("SELECT current_user, session_user").fetchone()
    log(f"Connected as: current_user={current_role[0]}, session_user={current_role[1]}")
    log("")

    rows = conn.execute("""
        SELECT
            c.relname                         AS table_name,
            c.relrowsecurity                  AS rls_enabled,
            c.relforcerowsecurity             AS rls_forced,
            COUNT(p.polname)                  AS policy_count
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_policy p ON p.polrelid = c.oid
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
        GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity
        ORDER BY c.relname
    """).fetchall()

    log("=== RLS status for all public tables ===")
    log(f"  {'Table':<28} {'RLS enabled':<14} {'RLS forced':<12} {'Policies'}")
    log("  " + "-" * 65)
    for tbl, rls_on, rls_forced, pol_count in rows:
        log(f"  {tbl:<28} {str(rls_on):<14} {str(rls_forced):<12} {pol_count}")

log("")
log("Audit complete. Nothing was modified.")

text = "\n".join(lines)
OUT.write_text(text, encoding="utf-8")
print(f"Written to {OUT}\n")
print(text)
