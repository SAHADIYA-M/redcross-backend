"""Test PsycopgUserRepository integration with Supabase DB."""

import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load .env
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.psycopg_user_repository import PsycopgUserRepository


def main():
    settings = get_settings()
    if not settings.database_url:
        print("[FAIL] DATABASE_URL is not set.")
        sys.exit(1)

    print("Testing PsycopgUserRepository with Supabase...")
    repo = PsycopgUserRepository(settings.database_url)

    # Generate unique test username
    test_uname = f"test_user_{uuid.uuid4().hex[:6]}"
    test_password = "SecurePassword123!"

    print(f"1. Creating test user '{test_uname}' via repository...")
    user = User(
        user_id=uuid.uuid4().hex,
        username=test_uname,
        password_hash=hash_password(test_password),
        full_name="Test User",
        role=UserRole.VIEWER,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    created = repo.create_user(user)
    print(f"   [OK] Created user_id: {created.user_id}")

    print(f"2. Testing case-insensitive lookup for '{test_uname.upper()}'...")
    user_by_uname = repo.get_by_username(test_uname.upper())
    assert user_by_uname is not None
    assert user_by_uname.user_id == created.user_id
    print(f"   [OK] Retrieved successfully by uppercase username.")

    print(f"3. Testing lookup by id '{created.user_id}'...")
    user_by_id = repo.get_by_id(created.user_id)
    assert user_by_id is not None
    assert user_by_id.username == test_uname
    print("   [OK] Retrieved successfully by id.")

    print(f"4. Cleaning up test user '{created.user_id}' from database...")
    import psycopg
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s;", (created.user_id,))
            conn.commit()
    print("   [OK] Test user deleted successfully.")

    print("\n✓ ALL TESTS PASSED! PsycopgUserRepository is fully working with Supabase.")


if __name__ == "__main__":
    main()