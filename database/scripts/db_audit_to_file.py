"""
db_audit_to_file.py
-------------------
Dumps a full READ-ONLY audit of the live Supabase DB to
database/scripts/audit_result.txt (UTF-8, no encoding issues).

Usage:  .venv/Scripts/python.exe database/scripts/db_audit_to_file.py
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV, override=False)
DB_URL = os.environ.get("DATABASE_URL", "")
if not DB_URL:
    sys.exit("DATABASE_URL not in .env")

import psycopg

OUT = Path(__file__).parent / "audit_result.txt"
lines = []
log = lines.append

EXPECTED = [
    "needs","priority","responders","locations","field_reports",
    "report_needs","affected_people","evidence",
    "report_clusters","cluster_members","verifications","users",
]

with psycopg.connect(DB_URL, prepare_threshold=None) as conn:
    existing = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'"
    ).fetchall()}

    log("=== Table existence ===")
    all_ok = True
    for t in EXPECTED:
        status = "[OK]" if t in existing else "[MISSING]"
        if t not in existing:
            all_ok = False
        log(f"  {t:<28} {status}")
    log("")
    log("All tables present." if all_ok else "WARNING: some tables are MISSING.")

    log("")
    log("=== Row counts ===")
    for t in EXPECTED:
        if t not in existing:
            log(f"  {t:<28} (missing)")
            continue
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        log(f"  {t:<28} {n:>5} rows")

    if "field_reports" in existing:
        log("")
        log("=== Embedding status (field_reports) ===")
        total, with_e, without_e = conn.execute(
            "SELECT COUNT(*), COUNT(embedding), "
            "COUNT(*) FILTER (WHERE embedding IS NULL) FROM field_reports"
        ).fetchone()
        log(f"  Total         : {total}")
        log(f"  Has embedding : {with_e}")
        log(f"  Missing       : {without_e}")
        if without_e:
            log("  ACTION NEEDED: run embed_reports.py")
        else:
            log("  All reports have embeddings.")

    if "users" in existing:
        log("")
        log("=== users indexes ===")
        for name, defn in conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND tablename='users' ORDER BY indexname"
        ).fetchall():
            log(f"  {name}")
            log(f"    {defn}")

log("")
log("Audit complete. Nothing was modified.")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Results written to {OUT}")
print("\n".join(lines))
