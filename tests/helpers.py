"""Shared, deterministic authentication fixtures for the test suite.

One in-memory user repository is created per test with exactly one user per
role (all with the same password), so every test can instantly obtain an
access token for any role without duplicating registration setup. The app's
user-repository dependency is overridden to the same repository so request
authentication resolves against these seeded users.

The shared password is a test-only value; it is never a production secret.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.models.user import User, UserRole
from app.repositories import InMemoryUserRepository
from app.schemas.auth import UserCreate
from app.services.auth_service import AuthService

DEV_PASSWORD = "password"


def make_auth_setup() -> SimpleNamespace:
    """Build a fresh user repository seeded with one user per role.

    Returns a namespace with ``repository`` (the seeded repository),
    ``service`` (the auth service over it) and ``users`` (role -> User).
    """
    repository = InMemoryUserRepository()
    service = AuthService(repository)
    users: dict[UserRole, User] = {}
    for role in UserRole:
        user = service.register(
            UserCreate(
                username=f"{role.value.lower()}_user",
                password=DEV_PASSWORD,
                full_name=f"{role.value.title()} Test User",
            ),
            role=role,
        )
        users[role] = user
    return SimpleNamespace(repository=repository, service=service, users=users)


def override_user_repository(setup: SimpleNamespace) -> None:
    """Point the app's user-repository dependency at the seeded repository."""
    from app.api.deps import get_user_repository
    from app.main import app

    app.dependency_overrides[get_user_repository] = lambda: setup.repository


def clear_user_repository_override() -> None:
    """Remove the user-repository dependency override, if present."""
    from app.api.deps import get_user_repository
    from app.main import app

    app.dependency_overrides.pop(get_user_repository, None)


def headers_for(setup: SimpleNamespace, role: UserRole) -> dict[str, str]:
    """Bearer authorization headers for the seeded user of the given role."""
    from app.core.security import create_access_token

    user = setup.users[role]
    token = create_access_token(subject=user.user_id, role=role.value)
    return {"Authorization": f"Bearer {token}"}


def attach_auth(
    client: TestClient, setup: SimpleNamespace, role: UserRole = UserRole.ADMIN
) -> TestClient:
    """Attach bearer headers for the given role to the client in place."""
    client.headers.update(headers_for(setup, role))
    return client