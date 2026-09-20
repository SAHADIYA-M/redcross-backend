"""Authentication API.

POST /api/auth/register - public registration. Never escalates role.
POST /api/auth/login    - public login; issues a bearer access token.
GET  /api/auth/me       - authenticated; returns the caller's safe profile.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_auth_service,
    get_current_active_user,
    get_current_user,
)
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.services.auth_service import (
    AuthService,
    DuplicateUserError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    data: UserCreate,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Register a new public user (always the configured default role).

    Duplicate usernames return 409. Registration never accepts a role: asking
    for ADMIN is rejected so privilege escalation through registration is
    impossible.
    """
    try:
        user = service.register(data)
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Log in and obtain a bearer access token.

    Credential failures all return the same generic 401 so the response never
    reveals whether a username exists. Inactive accounts cannot log in.
    """
    try:
        user = service.authenticate(data.username, data.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        ) from exc
    token = create_access_token(
        subject=user.user_id,
        role=user.role.value,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=CurrentUserResponse)
def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CurrentUserResponse:
    """Return the authenticated user's safe public profile."""
    return CurrentUserResponse.model_validate(current_user)