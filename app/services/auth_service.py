"""User management business logic.

Layers: API -> AuthService -> UserRepository interface ->
InMemoryUserRepository (today) -> database implementation (later).

Responsibilities:
- identity lookups (by id / username);
- listing users;
- updates (role assignment, activation, name). The final-admin lockout guard
  is preserved so the system can never be left without an active admin.
"""

import uuid
from datetime import datetime, timezone

from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.auth import UserUpdate


class UserNotFoundError(Exception):
    """Raised when a user with the requested id does not exist."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        super().__init__(f"User '{user_id}' not found")


class DuplicateUserError(Exception):
    """Raised when a user with the same username already exists."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"User '{username}' already exists")


class SelfModificationError(Exception):
    """Raised when the actor attempts to deactivate or demote themselves."""


class FinalAdminLockoutError(Exception):
    """Raised when an action would leave the system with no active admins."""


class AuthService:
    """Orchestrates user management.

    Depends only on the UserRepository interface, so storage can be swapped
    for a database later without changing this layer.
    """

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def get_by_id(self, user_id: str) -> User:
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def get_by_username(self, username: str) -> User | None:
        return self._repository.get_by_username(username.strip().casefold())

    def list_users(self) -> list[User]:
        return self._repository.list_users()

    def update_user(
        self,
        user_id: str,
        data: UserUpdate,
        actor_id: str | None = None,
    ) -> User:
        """Apply changes (role assignment, activation, name).

        Only the supplied fields change; identity (user_id/username) and the
        password hash are never touchable here. When ``actor_id`` is supplied
        and equals the target user, self-demotion/deactivation is rejected.
        """
        existing = self._repository.get_by_id(user_id)
        if existing is None:
            raise UserNotFoundError(user_id)

        is_modifying_role = data.role is not None and data.role != existing.role
        is_deactivating = data.is_active is False and existing.is_active is True

        if (
            actor_id is not None
            and (is_modifying_role or is_deactivating)
            and user_id == actor_id
        ):
            raise SelfModificationError(
                "Administrators cannot downgrade or deactivate themselves"
            )

        if (
            existing.is_active
            and existing.role == UserRole.ADMIN
            and (is_modifying_role or is_deactivating)
        ):
            admins = [
                u
                for u in self.list_users()
                if u.role == UserRole.ADMIN and u.is_active
            ]
            if len(admins) <= 1:
                raise FinalAdminLockoutError(
                    "Cannot modify or deactivate the final active administrator"
                )

        updated = User(
            user_id=existing.user_id,
            username=existing.username,
            password_hash=existing.password_hash,
            full_name=(
                data.full_name if data.full_name is not None else existing.full_name
            ),
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