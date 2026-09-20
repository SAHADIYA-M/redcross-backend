from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """Controlled role of a backend user.

    Roles are the only thing authorization depends on. They deliberately form
    a small set appropriate for a student/hackathon MVP:
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


# Roles that may create or update reports (i.e. every role except read-only
# VIEWER). ADMIN always passes every check by construction.
REPORT_WRITER_ROLES = frozenset(
    {UserRole.ADMIN, UserRole.ASSESSOR, UserRole.REVIEWER, UserRole.RESPONDER}
)

# Roles allowed to perform human verification / request assessment.
REVIEWER_ROLES = frozenset({UserRole.REVIEWER, UserRole.ADMIN})

# Roles allowed to create or update response activities.
RESPONDER_ROLES = frozenset({UserRole.RESPONDER, UserRole.ADMIN})


class User(BaseModel):
    """Backend representation of an authenticated API user.

    Identifies WHO is making a request. Passwords are never stored in
    plaintext: only the bcrypt hash is persisted, and the hash is never
    exposed through public API responses. This entity is database-independent
    so the API can be developed before the real database is available.
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