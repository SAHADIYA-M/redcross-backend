"""PsycopgUserRepository for RedCross Nexus — PostgreSQL user persistence using psycopg (v3)."""

from __future__ import annotations

import psycopg
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository


class PsycopgUserRepository(UserRepository):
    """PostgreSQL implementation of UserRepository using psycopg (v3)."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create_user(self, user: User) -> User:
        """Persist a new user into PostgreSQL."""
        query = """
            INSERT INTO users (user_id, username, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, %s, %s);
        """
        with psycopg.connect(self._database_url, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        user.user_id,
                        user.username,
                        user.password_hash,
                        user.full_name,
                        user.role.value if isinstance(user.role, UserRole) else str(user.role),
                        user.is_active,
                    ),
                )
                conn.commit()
        return user

    def get_by_id(self, user_id: str) -> User | None:
        """Return the user with the given user_id, or None if not found."""
        query = """
            SELECT user_id, username, password_hash, full_name, role, is_active
            FROM users
            WHERE user_id = %s;
        """
        with psycopg.connect(self._database_url, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (user_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return User(
                    user_id=row[0],
                    username=row[1],
                    password_hash=row[2],
                    full_name=row[3],
                    role=UserRole(row[4]),
                    is_active=row[5],
                )

    def get_by_username(self, username: str) -> User | None:
        """Return the user with the given username (case-insensitive), or None."""
        query = """
            SELECT user_id, username, password_hash, full_name, role, is_active
            FROM users
            WHERE lower(username) = lower(%s);
        """
        with psycopg.connect(self._database_url, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (username,))
                row = cur.fetchone()
                if not row:
                    return None
                return User(
                    user_id=row[0],
                    username=row[1],
                    password_hash=row[2],
                    full_name=row[3],
                    role=UserRole(row[4]),
                    is_active=row[5],
                )

    def list_users(self) -> list[User]:
        """Return all stored users."""
        query = """
            SELECT user_id, username, password_hash, full_name, role, is_active
            FROM users;
        """
        users = []
        with psycopg.connect(self._database_url, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                for row in cur.fetchall():
                    users.append(
                        User(
                            user_id=row[0],
                            username=row[1],
                            password_hash=row[2],
                            full_name=row[3],
                            role=UserRole(row[4]),
                            is_active=row[5],
                        )
                    )
        return users

    def update_user(self, user: User) -> User | None:
        """Replace stored user record in PostgreSQL."""
        query = """
            UPDATE users
            SET username = %s, password_hash = %s, full_name = %s, role = %s, is_active = %s
            WHERE user_id = %s;
        """
        with psycopg.connect(self._database_url, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        user.username,
                        user.password_hash,
                        user.full_name,
                        user.role.value if isinstance(user.role, UserRole) else str(user.role),
                        user.is_active,
                        user.user_id,
                    ),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
        return user
