from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """Controlled role of a backend user.

    Roles deliberately form a small set appropriate for a student/hackathon
    MVP. With the API unauthenticated they are attributes of stored user
    records; they drive user-management guards (e.g. the final-admin lockout)
    but do not gate HTTP access.
    - ADMIN     : full backend access; may perform any other role's actions.
    - ASSESSOR  : submits/updates reports and requests assessments.
    - REVIEWER  : performs human verification and review actions.
    - RESPONDER : creates/updates response activities and views operations.
    - VIEWER    : read-only access to operational information.
    """

    ADMIN = "ADMIN"
    ASSESSOR = "ASSESSOR"
    REVIEWER = "REVIEWER"
    RESPONDER = "RESPONDER"
    VIEWER = "VIEWER"


class User(BaseModel):
    """Database-independent representation of a stored user record.

    Passwords are never stored in plaintext: only the bcrypt hash is
    persisted, and the hash is never exposed through public API responses.
    """

    user_id: str
    username: str
    password_hash: str
    full_name: str | None = None
    role: UserRole = UserRole.VIEWER
    is_active: bool = True
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )