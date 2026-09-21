"""Authentication business logic.

Layers: API -> AuthService -> UserRepository interface ->
InMemoryUserRepository (today) -> database implementation (later).

Responsibilities:
- registration. The public register path can never escalate privileges: the
  caller-supplied data has no role field and the role defaults to the
  configured public role. Internal creation can pass an explicit role (used
  only by the admin-only user management and the development seed).
- login. Password verification uses bcrypt; failures are intentionally
  indistinct (no account enumeration, no "wrong password" vs "no user").
- identity lookups and admin-only updates (role assignment / activation).
- a development-only admin seed that is never active in production and is
  only created when an explicit environment setting is enabled.
"""

import uuid
from datetime import datetime, timezone

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, UserCreate, UserUpdate


class DuplicateUserError(Exception):
    """Raised when a username is already registered."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"Username '{username}' is already registered")


class UserNotFoundError(Exception):
    """Raised when a user with the requested id does not exist."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        super().__init__(f"User '{user_id}' not found")


class SelfModificationError(Exception):
    """Raised when an admin attempts to deactivate or demote themselves."""


class FinalAdminLockoutError(Exception):
    """Raised when an action would leave the system with no active admins."""


class InvalidCredentialsError(Exception):
    """Raised when a login attempt does not match any active account.

    Deliberately carries no information about whether the username exists: a
    generic failure message is the only thing ever revealed.
    """


class AuthService:
    """Orchestrates registration, login and user management.

    Depends only on the UserRepository interface, so storage can be swapped
    for a database later without changing this layer.
    """

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def register(
        self, data: UserCreate, *, role: UserRole | None = None
    ) -> User:
        """Create a user with a hashed password.

        An explicit ``role`` is only accepted from internal callers (the
        admin-only management layer and the development seed); the public API
        never supplies one, so it can never register an ADMIN.
        """
        username = data.username.strip().casefold()
        if self._repository.get_by_username(username) is not None:
            raise DuplicateUserError(username)
        assigned_role = role or self._default_public_role()
        user = User(
            user_id=uuid.uuid4().hex,
            username=username,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=assigned_role,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        return self._repository.create_user(user)

    def authenticate(
        self, username_or_req: str | LoginRequest, password: str | None = None
    ) -> User:
        """Validate credentials and return the account (inactive excluded)."""
        if isinstance(username_or_req, LoginRequest):
            username = username_or_req.username
            password = username_or_req.password
        else:
            username = username_or_req
            if password is None:
                raise InvalidCredentialsError()

        user = self._repository.get_by_username(username.strip().casefold())
        if user is None or not user.is_active:
            raise InvalidCredentialsError()
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        return user

    def get_by_id(self, user_id: str) -> User:
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def get_by_username(self, username: str) -> User | None:
        return self._repository.get_by_username(username.strip().casefold())

    def list_users(self) -> list[User]:
        return self._repository.list_users()

    def update_user(self, user_id: str, data: UserUpdate, actor_id: str) -> User:
        """Apply admin-only changes (role assignment, activation, name).

        Only the supplied fields change; identity (user_id/username) and the
        password hash are never touchable here.
        """
        existing = self._repository.get_by_id(user_id)
        if existing is None:
            raise UserNotFoundError(user_id)
            
        is_modifying_role = data.role is not None and data.role != existing.role
        is_deactivating = data.is_active is False and existing.is_active is True
        
        if (is_modifying_role or is_deactivating) and user_id == actor_id:
            raise SelfModificationError("Administrators cannot downgrade or deactivate themselves")
            
        if existing.role == UserRole.ADMIN and (is_modifying_role or is_deactivating):
            admins = [u for u in self.list_users() if u.role == UserRole.ADMIN and u.is_active]
            if len(admins) <= 1:
                raise FinalAdminLockoutError("Cannot modify or deactivate the final active administrator")

        updated = User(
            user_id=existing.user_id,
            username=existing.username,
            password_hash=existing.password_hash,
            full_name=data.full_name
            if data.full_name is not None
            else existing.full_name,
            role=data.role if data.role is not None else existing.role,
            is_active=(
                data.is_active if data.is_active is not None else existing.is_active
            ),
            created_at=existing.created_at,
        )
        stored = self._repository.update_user(updated)
        if stored is None:
            raise UserNotFoundError(user_id)
        return stored

    def _default_public_role(self) -> UserRole:
        try:
            return UserRole(settings.public_register_role)
        except ValueError:
            return UserRole.VIEWER


def seed_development_admin(service: AuthService) -> None:
    """Create a development admin only when explicitly enabled.

    Guards:
    - never runs in production;
    - only runs when SEED_DEV_ADMIN is enabled;
    - requires a username/password to exist in the environment;
    - credentials are development-only and must never be used in production.
    """
    if settings.environment == "production" or not settings.seed_dev_admin:
        return
    username = settings.dev_admin_username.strip()
    password = settings.dev_admin_password
    if not username or not password or len(password) < 8:
        return
    if service.get_by_username(username) is not None:
        return
    service.register(
        UserCreate(
            username=username,
            password=password,
            full_name="Development Administrator",
        ),
        role=UserRole.ADMIN,
    )