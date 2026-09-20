"""
embed_reports.py
----------------
Reads every row in field_reports that is missing an embedding (or all rows
when --force is given), generates a 768-dim embedding via embed_text(), and
saves it back to field_reports.embedding.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    sys.exit("DATABASE_URL not found in .env — aborting.")

from embedding_utils import embed_text

try:
    import psycopg
    from pgvector.psycopg import register_vector
except ImportError as exc:
    sys.exit(
        f"Missing dependency: {exc}\n"
        "Install with: pip install psycopg[binary] pgvector"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed field_reports.raw_content with Gemini and store "
                    "the result in field_reports.embedding."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed rows that already have an embedding.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with psycopg.connect(
        _DATABASE_URL,
        prepare_threshold=None,
        autocommit=False,
    ) as conn:
        register_vector(conn)

        query = (
            "SELECT report_id, raw_content FROM field_reports ORDER BY reported_at"
            if args.force
            else "SELECT report_id, raw_content FROM field_reports WHERE embedding IS NULL ORDER BY reported_at"
        )

        cur = conn.execute(query)
        rows = cur.fetchall()

        if not rows:
            print("No rows to embed — all up to date.")
            return

        print(f"Embedding {len(rows)} report(s) ({'--force mode' if args.force else 'missing only'}) …")

        ok = 0
        errors = 0

        for report_id, raw_content in rows:
            try:
                vector = embed_text(raw_content)
            except Exception as exc:
                print(f"  [ERROR] {report_id}: {exc}", file=sys.stderr)
                errors += 1
                continue

            conn.execute(
                "UPDATE field_reports SET embedding = %s WHERE report_id = %s",
                (vector, report_id),
            )
            conn.commit()
            ok += 1
            print(f"  [OK]    {report_id}")

        print(
            f"\nDone — {ok} embedded, {errors} error(s)."
            + (" Run again to retry failed rows." if errors else "")
        )


if __name__ == "__main__":
    main()
