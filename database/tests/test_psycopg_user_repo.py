"""Test PsycopgUserRepository and AuthService integration with Supabase DB."""

import os
import sys
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Load .env
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import get_settings
from app.models.user import User, UserRole
from app.repositories.psycopg_user_repository import PsycopgUserRepository
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService


def main():
    settings = get_settings()
    if not settings.database_url:
        print("[FAIL] DATABASE_URL is not set.")
        sys.exit(1)

    print("Testing PsycopgUserRepository with Supabase...")
    repo = PsycopgUserRepository(settings.database_url)
    auth_service = AuthService(repo)

    # Generate unique test username
    test_uname = f"test_user_{uuid.uuid4().hex[:6]}"
    test_password = "SecurePassword123!"

    print(f"1. Registering test user '{test_uname}' via AuthService...")
    from app.schemas.auth import RegisterRequest
    reg_req = RegisterRequest(
        username=test_uname,
        password=test_password,
        full_name="Test User",
        role=UserRole.VIEWER
    )
    reg_res = auth_service.register(reg_req)
    print(f"   [OK] Registered user_id: {reg_res.user_id}")

    print(f"2. Authenticating user '{test_uname}'...")
    login_req = LoginRequest(username=test_uname, password=test_password)
    login_res = auth_service.authenticate(login_req)
    print(f"   [OK] Authentication successful! Token generated, role: {login_res.role}")

    print(f"3. Testing case-insensitive lookup for '{test_uname.upper()}'...")
    user_by_uname = repo.get_by_username(test_uname.upper())
    assert user_by_uname is not None
    assert user_by_uname.user_id == reg_res.user_id
    print(f"   [OK] Retrieved successfully by uppercase username.")

    print(f"4. Cleaning up test user '{reg_res.user_id}' from database...")
    import psycopg
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s;", (reg_res.user_id,))
            conn.commit()
    print("   [OK] Test user deleted successfully.")

    print("\n✓ ALL TESTS PASSED! PsycopgUserRepository is fully working with Supabase.")


if __name__ == "__main__":
    main()
