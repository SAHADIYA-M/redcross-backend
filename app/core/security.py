"""Authentication primitives: password hashing and signed access tokens.

Security invariants held here (and enforced by the rest of the auth layer):
- passwords are never stored, returned or logged in plaintext; only bcrypt
  hashes are persisted and the JWT payload carries identity only;
- the JWT signing secret always comes from the environment (never hardcoded);
- tokens carry an expiry (``exp``) that decode strictly enforces;
- tokens contain identity info (sub/role), never passwords, hashes or
  sensitive report content.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

_ALGORITHMS = [settings.jwt_algorithm]
_TOKEN_TYPE = "bearer"

_INSECURE_TOKEN_REASON = (
    "A valid access token for this user could not be produced or decoded."
)


class TokenError(Exception):
    """Raised when a token is malformed, tampered with, expired or unusable."""


def _jwt_secret() -> str:
    secret = settings.effective_jwt_secret_key()
    if not secret:
        raise TokenError("JWT secret is not configured")
    return secret


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given plaintext password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Return True when the plaintext password matches the stored hash."""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except ValueError:
        return False


def create_access_token(
    *,
    subject: str,
    role: str,
    expires_minutes: int | None = None,
) -> str:
    """Create a signed access token carrying only identity claims.

    ``sub`` carries the user id, ``role`` the current role value (declared
    here so a client never controls it), and ``exp`` the absolute expiry. No
    password, hash, personal or report data is ever embedded.
    """
    now = datetime.now(timezone.utc)
    lifetime = timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, object]:
    """Decode and validate an access token.

    Raises :class:`TokenError` for any unusable token (expired, invalid
    signature, missing required claims, malformed). The ``exp``/``sub`` claims
    are required, so an expired token can never pass.
    """
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=_ALGORITHMS,
            options={"require": ["exp", "sub"]},
        )
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise TokenError(_INSECURE_TOKEN_REASON) from exc
    return payload