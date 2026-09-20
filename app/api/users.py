"""Admin-only user management API.

GET   /api/users            - list all users (ADMIN only).
PATCH /api/users/{user_id}  - assign role / toggle active (ADMIN only).

Role assignment is deliberately restricted to this admin-only mechanism so a
normal registered user can never escalate their own role.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_auth_service, require_roles
from app.models.user import User, UserRole
from app.schemas.auth import UserResponse, UserUpdate
from app.services.auth_service import AuthService, UserNotFoundError

router = APIRouter(prefix="/api/users", tags=["users"])

_require_admin = require_roles(UserRole.ADMIN)


@router.get("", response_model=list[UserResponse])
def list_users(
    _admin: Annotated[User, Depends(_require_admin)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> list[UserResponse]:
    """List every registered user (ADMIN only)."""
    return [UserResponse.model_validate(user) for user in service.list_users()]


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    data: UserUpdate,
    _admin: Annotated[User, Depends(_require_admin)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Assign a role and/or toggle activation for a user (ADMIN only)."""
    try:
        user = service.update_user(user_id, data)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return UserResponse.model_validate(user)