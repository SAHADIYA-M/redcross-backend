from abc import ABC, abstractmethod

from app.models.user import User


class UserRepository(ABC):
    """Contract for storing and retrieving backend users.

    The auth API and service layers depend on this interface only. Concrete
    implementations (in-memory today, PostgreSQL later) can be swapped without
    changing the rest of the application.

    Passwords are only ever stored as hashes; no repository method accepts or
    returns a plaintext password.
    """

    @abstractmethod
    def create_user(self, user: User) -> User:
        """Persist a new user and return it."""

    @abstractmethod
    def get_by_id(self, user_id: str) -> User | None:
        """Return the user with the given id, or None if not found."""

    @abstractmethod
    def get_by_username(self, username: str) -> User | None:
        """Return the user with the given username (case-insensitive), or None."""

    @abstractmethod
    def list_users(self) -> list[User]:
        """Return all stored users."""

    @abstractmethod
    def update_user(self, user: User) -> User | None:
        """Replace the stored user with the given one; None if not found."""