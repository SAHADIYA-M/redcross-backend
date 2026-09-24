"""Verify the users table structure in Supabase."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import psycopg

url = os.environ["DATABASE_URL"]
with psycopg.connect(url, prepare_threshold=None) as conn:
    cols = conn.execute(
        """
        SELECT column_name, data_type, column_default, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'users'
        ORDER BY ordinal_position
        """
    ).fetchall()

    print("=== Columns of public.users ===")
    print(f"{'Column':<20} {'Type':<25} {'Default':<35} {'Nullable'}")
    print("-" * 85)
    for col_name, data_type, col_default, nullable in cols:
        print(
            f"{col_name:<20} {data_type:<25} {str(col_default or ''):<35} {nullable}"
        )

    idxs = conn.execute(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = 'users'
        ORDER BY indexname
        """
    ).fetchall()

    print()
    print("=== Indexes on public.users ===")
    for idx_name, idx_def in idxs:
        print(f"  {idx_name}")
        print(f"    {idx_def}")

    constraints = conn.execute(
        """
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'public.users'::regclass
        ORDER BY conname
        """
    ).fetchall()

    print()
    print("=== Constraints on public.users ===")
    for con_name, con_def in constraints:
        print(f"  {con_name}: {con_def}")
