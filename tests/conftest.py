"""Pytest fixtures shared across the whole test suite (Phase 13 auth setup).

``auth_setup`` seeds an in-memory user repository with one user per role and
overrides the app's user-repository dependency, so any TestClient issued
against ``app`` resolves bearer tokens against those seeded users. The role
header fixtures return ready-to-attach Authorization headers.
"""

import bcrypt
import pytest

import app.services.auth_service as auth_service_module
from app.models.user import UserRole
from tests.helpers import (
    clear_user_repository_override,
    headers_for,
    make_auth_setup,
    override_user_repository,
)


def _fast_hash_password(password: str) -> str:
    """Test-only bcrypt hashing at a very low cost factor.

    Seeding users runs once per fixture-using test; the default cost (rounds
    = 12) would add roughly 1.2s of hashing to every single test. The cost
    factor is a security/performance trade-off that is irrelevant to the
    behaviour under test, so tests force rounds=4. verify_password reads the
    cost from the stored hash, so login checks stay consistent.
    """
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=4)
    ).decode("utf-8")


auth_service_module.hash_password = _fast_hash_password


@pytest.fixture()
def auth_setup():
    """Fresh seeded users (one per role) wired to the live app.

    Both the user-repository AND the auth-service dependencies point at the
    seeded repository, so request authentication, API registration and API
    login all operate on exactly the same in-memory data as the seeded users.
    """
    from app.api.deps import get_auth_service, get_user_repository
    from app.main import app

    setup = make_auth_setup()
    override_user_repository(setup)
    app.dependency_overrides[get_auth_service] = lambda: setup.service
    yield setup
    app.dependency_overrides.pop(get_auth_service, None)
    clear_user_repository_override()


@pytest.fixture()
def admin_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.ADMIN)


@pytest.fixture()
def assessor_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.ASSESSOR)


@pytest.fixture()
def reviewer_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.REVIEWER)


@pytest.fixture()
def responder_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.RESPONDER)


@pytest.fixture()
def viewer_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.VIEWER)