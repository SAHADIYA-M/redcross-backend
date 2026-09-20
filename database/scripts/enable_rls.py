"""
enable_rls.py
-------------
Enables Row Level Security (RLS) on all tables in the public schema.

WHY this is needed:
  Supabase exposes every table through its built-in REST API (PostgREST).
  Without RLS, anyone with your project URL + anon key can read/write
  all tables directly — including password hashes in `users`.
  Enabling RLS blocks ALL PostgREST/anon access by default.

WHY this is safe for the backend:
  The FastAPI backend connects as the `postgres` superuser (via the
  Transaction pooler DATABASE_URL). PostgreSQL superusers ALWAYS bypass
  RLS, so the backend is completely unaffected.

WHAT this script does:
  - ALTER TABLE ... ENABLE ROW LEVEL SECURITY  on every table
  - Nothing else. No rows are changed. No policies are added.
  - Prints a before/after confirmation.

Usage:  .venv/Scripts/python.exe database/scripts/enable_rls.py
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env", override=False)
DB_URL = os.environ.get("DATABASE_URL", "")
if not DB_URL:
    sys.exit("DATABASE_URL not in .env")

import psycopg

# Tables to protect — every table in the schema
TABLES = [
    "users",
    "needs",
    "priority",
    "responders",
    "locations",
    "field_reports",
    "report_needs",
    "affected_people",
    "evidence",
    "report_clusters",
    "cluster_members",
    "verifications",
]

OUT = Path(__file__).parent / "rls_enable_result.txt"
lines = []
log = lines.append

log("Enabling Row Level Security on all public tables ...")
log("")

with psycopg.connect(DB_URL, prepare_threshold=None) as conn:
    role = conn.execute("SELECT current_user").fetchone()[0]
    log(f"Connected as: {role}")
    log("")

    for tbl in TABLES:
        conn.execute(f"ALTER TABLE public.{tbl} ENABLE ROW LEVEL SECURITY")
        log(f"  [OK] RLS enabled on: {tbl}")

    conn.commit()
    log("")

    # Verify
    log("=== Verification — RLS status after change ===")
    log(f"  {'Table':<28} {'RLS enabled':<14} {'Policies'}")
    log("  " + "-" * 50)
    rows = conn.execute("""
        SELECT
            c.relname,
            c.relrowsecurity,
            COUNT(p.polname) AS policy_count
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_policy p ON p.polrelid = c.oid
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        GROUP BY c.relname, c.relrowsecurity
        ORDER BY c.relname
    """).fetchall()

    all_on = True
    for tbl_name, rls_on, pol_count in rows:
        status = "[ON]" if rls_on else "[OFF]"
        if not rls_on:
            all_on = False
        log(f"  {tbl_name:<28} {status:<14} {pol_count} polic(ies)")

    log("")
    if all_on:
        log("All tables now have RLS enabled.")
        log("The postgres superuser (backend) is unaffected.")
        log("Supabase REST/PostgREST anon access is now blocked on all tables.")
    else:
        log("WARNING: some tables still have RLS disabled.")

text = "\n".join(lines)
OUT.write_text(text, encoding="utf-8")
print(f"Written to {OUT}\n")
print(text)
