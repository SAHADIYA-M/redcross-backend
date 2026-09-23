"""Password hashing primitives for the stored user records.

Passwords are never stored, returned or logged in plaintext; only bcrypt
hashes are persisted. Hashing is used purely when creating/seeding user
records in the users table — the API itself is unauthenticated and never
signs or verifies tokens.
"""

import bcrypt


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given plaintext password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )
