"""Request/response schemas for user management.

Public responses never expose password hashes or any internal credential
field.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import UserRole
from app.schemas.lengths import MAX_FULL_NAME_LENGTH, MAX_PASSWORD_LENGTH


class UserCreate(BaseModel):
    """Payload for creating a user record (internal / seeding use).

    A role is never accepted here: an elevated role is assigned only through
    the user-management update endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)
    full_name: str | None = Field(default=None, max_length=MAX_FULL_NAME_LENGTH)

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
    """Body for updating a user (role assignment / activation)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=MAX_FULL_NAME_LENGTH)
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