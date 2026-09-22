"""Admin-only user management API.

GET   /api/users            - list all users (ADMIN only).
PATCH /api/users/{user_id}  - assign role / toggle active (ADMIN only).

Role assignment is deliberately restricted to this admin-only mechanism so a
normal registered user can never escalate their own role.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_auth_service, require_roles
from app.models.user import User, UserRole
from app.schemas.auth import UserResponse, UserUpdate
from app.schemas.lengths import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from app.services.auth_service import (
    AuthService,
    UserNotFoundError,
    SelfModificationError,
    FinalAdminLockoutError,
)

router = APIRouter(prefix="/api/users", tags=["users"])

_require_admin = require_roles(UserRole.ADMIN)


@router.get("", response_model=list[UserResponse])
def list_users(
    _admin: Annotated[User, Depends(_require_admin)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> list[UserResponse]:
    """List every registered user (ADMIN only), bounded page of ``limit``."""
    return [
        UserResponse.model_validate(user)
        for user in service.list_users()[offset : offset + limit]
    ]


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    data: UserUpdate,
    _admin: Annotated[User, Depends(_require_admin)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Assign a role and/or toggle activation for a user (ADMIN only)."""
    try:
        user = service.update_user(user_id, data, _admin.user_id)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SelfModificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except FinalAdminLockoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return UserResponse.model_validate(user)