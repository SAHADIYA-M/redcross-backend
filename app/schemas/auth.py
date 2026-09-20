"""Request/response schemas for authentication and user management.

Public responses never expose password hashes or any internal credential
field. Registration deliberately has no ``role`` field: a client can never
self-assign an elevated role (privilege escalation is impossible by design).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import UserRole


class UserCreate(BaseModel):
    """Body of POST /api/auth/register.

    ``role`` is intentionally absent: public registration always creates the
    configured default role (VIEWER). Role assignment is an admin-only
    mechanism.
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=128)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("username must not be blank")
        return stripped

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        if len(value.encode('utf-8')) > 72:
            raise ValueError("password must be 72 bytes or fewer")
        return value


class UserUpdate(BaseModel):
    """Admin-only body for updating a user (role assignment / activation)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _require_change(self) -> "UserUpdate":
        if (
            self.full_name is None
            and self.role is None
            and self.is_active is None
        ):
            raise ValueError("at least one field must be supplied")
        return self


class UserResponse(BaseModel):
    """Safe public representation of a user.

    Never includes ``password`` or ``password_hash``.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    username: str
    full_name: str | None = None
    role: UserRole
    is_active: bool
    created_at: datetime


class CurrentUserResponse(UserResponse):
    """Returned by GET /api/auth/me (the authenticated caller)."""


class LoginRequest(BaseModel):
    """Body of POST /api/auth/login."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """Successful login response.

    The token is a bearer access token; ``token_type`` is always "bearer".
    Basic user information is included so a client can render the logged-in
    user without a second round trip.
    """

    access_token: str
    token_type: str = "bearer"
    user: UserResponse