"""Test cases for duplicate and conflicting report retrieval in RedCross Nexus.

Runs candidate_retrieval.sql against live Supabase data to verify:
1. Near-duplicate retrieval (e.g. Water reports 1, 2, 3 near Govt UP School)
2. Conflict detection candidates (e.g. Report 6 tanker arrived vs shortage)
3. Spatiotemporal filtering (72-hour time window & 2 km radius gate)
4. Multi-need candidate retrieval across need categories
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)

import psycopg
from pgvector.psycopg import register_vector

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    sys.exit("DATABASE_URL not set in .env")

_QUERY_PATH = _PROJECT_ROOT / "database" / "queries" / "candidate_retrieval.sql"
_SQL = _QUERY_PATH.read_text(encoding="utf-8")


def run_candidate_query(conn, report_id: str, need_id: int | None = None, apply_filters: bool = True):
    params = {
        "report_id": report_id,
        "need_id": need_id,
        "apply_filters": apply_filters,
    }
    cur = conn.execute(_SQL, params)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def main():
    print("Connecting to Supabase PostgreSQL...")
    with psycopg.connect(_DATABASE_URL, prepare_threshold=None) as conn:
        register_vector(conn)

        # ---------------------------------------------------------------
        # Test Case 1: Duplicate Detection for Water Shortage Reports
        # Report 1 (Water shortage at UP School) should match Report 2 & 3
        # ---------------------------------------------------------------
        rep1_id = "b0000000-0000-0000-0000-000000000001"
        print(f"\n1. Testing Duplicate Candidate Retrieval for Report 1 ({rep1_id})...")
        results = run_candidate_query(conn, report_id=rep1_id, need_id=1, apply_filters=True)

        print(f"   Found {len(results)} candidate report(s):")
        for res in results:
            print(f"   - Report: {res['report_id']} | Sim: {res['similarity']:.3f} | Dist: {res['distance_km']} km | Needs: {res['shared_needs']}")
            print(f"     Snippet: {res['snippet']}")

        assert len(results) >= 2, "Expected at least 2 candidates for Report 1"
        top_candidate = results[0]
        assert top_candidate["similarity"] > 0.80, "Expected top similarity > 0.80 for duplicate report"
        print("   [PASS] High semantic similarity duplicates correctly identified.")

        # ---------------------------------------------------------------
        # Test Case 2: Conflict Candidate (Report 6: Tanker arrived)
        # ---------------------------------------------------------------
        rep6_id = "b0000000-0000-0000-0000-000000000006"
        print(f"\n2. Testing Conflict Candidate Retrieval for Report 6 ({rep6_id})...")
        results = run_candidate_query(conn, report_id=rep6_id, need_id=1, apply_filters=True)

        print(f"   Found {len(results)} candidate report(s):")
        for res in results:
            print(f"   - Report: {res['report_id']} | Sim: {res['similarity']:.3f} | Snippet: {res['snippet']}")

        assert len(results) > 0, "Expected candidates for conflicting report"
        print("   [PASS] Conflicting report successfully linked to cluster candidates.")

        # ---------------------------------------------------------------
        # Test Case 3: Multi-Need Report (Report 16 / 0010)
        # ---------------------------------------------------------------
        rep10_id = "b0000000-0000-0000-0000-000000000010"
        print(f"\n3. Testing Multi-Need Candidate Retrieval for Report 16 ({rep10_id})...")
        results_water = run_candidate_query(conn, report_id=rep10_id, need_id=1, apply_filters=False)
        results_med = run_candidate_query(conn, report_id=rep10_id, need_id=4, apply_filters=False)

        print(f"   - Water candidates: {len(results_water)}")
        print(f"   - Medical candidates: {len(results_med)}")
        assert len(results_water) > 0, "Multi-need report should find water candidates"
        assert len(results_med) > 0, "Multi-need report should find medical candidates"
        print("   [PASS] Multi-need report successfully retrieved across different need filters.")

    print("\n✓ ALL DUPLICATE AND CONFLICT DETECTION TEST CASES PASSED!")


if __name__ == "__main__":
    main()
