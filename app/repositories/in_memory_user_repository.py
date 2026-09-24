from app.models.user import User
from app.repositories.user_repository import UserRepository


class InMemoryUserRepository(UserRepository):
    """Temporary user store backed by an in-memory dictionary.

    Replaced by a PostgreSQL-backed repository in a later phase. Username
    lookups are case-insensitive so "Alice" and "alice" are the same account.
    """

    def __init__(self) -> None:
        self._store: dict[str, User] = {}
        self._by_username: dict[str, str] = {}

    def create_user(self, user: User) -> User:
        key = user.username.casefold()
        self._store[user.user_id] = user
        self._by_username[key] = user.user_id
        return user

    def get_by_id(self, user_id: str) -> User | None:
        return self._store.get(user_id)

    def get_by_username(self, username: str) -> User | None:
        user_id = self._by_username.get(username.casefold())
        return self._store.get(user_id) if user_id is not None else None

    def list_users(self) -> list[User]:
        return list(self._store.values())

    def update_user(self, user: User) -> User | None:
        if user.user_id not in self._store:
            return None
        self._store[user.user_id] = user
        self._by_username[user.username.casefold()] = user.user_id
        return user