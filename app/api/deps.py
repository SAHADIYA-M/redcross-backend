"""Reusable FastAPI dependencies for authentication and authorization.

- ``get_current_user``        -> identity: WHO made this request.
- ``get_current_active_user`` -> identity + inactive-account guard.
- ``require_roles(...)``      -> authorization: WHAT an active user may do.

HTTP status semantics:
- missing/invalid/expired token -> 401 Unauthorized;
- valid token but inactive user -> 403 Forbidden;
- authenticated but wrong role  -> 403 Forbidden.

The bearer security scheme is registered here, so every protected endpoint
appears in Swagger/OpenAPI under "HTTP bearer".
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.container import get_auth_service, get_user_repository
from app.core.security import TokenError, decode_access_token
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(_bearer_scheme)
    ],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    """Resolve the authenticated user from the bearer token.

    The token carries only ``sub`` (user id) plus a convenience role claim;
    the user record (including the authoritative role) is always loaded from
    the repository, so a stale or hand-crafted token cannot escalate.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload["sub"]
    except (TokenError, KeyError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    user = repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Like get_current_user, but inactive accounts are forbidden."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    """Build a dependency that only allows the given roles.

    Unauthenticated requests fail with 401 (via get_current_active_user);
    authenticated requests holding a different role fail with 403.
    """
    allowed = set(allowed_roles)

    def _require(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Insufficient role for this operation "
                    f"(required {sorted(r.value for r in allowed)})"
                ),
            )
        return current_user

    return _require