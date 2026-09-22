"""Batch 1 security configuration tests.

Covers the fail-closed JWT secret policy and the public-registration role
allow-list. The tests build fresh ``Settings`` instances from a controlled
environment so each environment/secret combination is exercised explicitly.

No test ever reads or prints the actual configured secret value: the JWT
assertions compare only against the known development fallback or a synthetic
test value.
"""

import pytest

from app.core.config import Settings, _DEV_ONLY_JWT_SECRET
from app.core.security import TokenError


def _build_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: str,
    jwt_secret: str | None,
    public_role: str | None = None,
) -> Settings:
    monkeypatch.setenv("ENVIRONMENT", environment)
    # Production forbids a wildcard CORS origin; use an explicit origin so the
    # JWT logic under test is the only thing that can fail.
    monkeypatch.setenv("CORS_ORIGINS", "https://example.org")
    if jwt_secret is None:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET_KEY", jwt_secret)
    if public_role is None:
        monkeypatch.delenv("PUBLIC_REGISTER_ROLE", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_REGISTER_ROLE", public_role)
    return Settings()


# ---------------------------------------------------------------------------
# JWT secret fail-closed behaviour
# ---------------------------------------------------------------------------


def test_development_missing_secret_uses_dev_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch, environment="development", jwt_secret=None
    )
    assert settings.effective_jwt_secret_key() == _DEV_ONLY_JWT_SECRET


def test_development_explicit_secret_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch, environment="development", jwt_secret="dev-explicit-secret"
    )
    assert settings.effective_jwt_secret_key() == "dev-explicit-secret"


def test_production_missing_secret_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch, environment="production", jwt_secret=None
    )
    with pytest.raises(TokenError):
        settings.effective_jwt_secret_key()


def test_production_explicit_secret_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch, environment="production", jwt_secret="real-production-secret"
    )
    assert settings.effective_jwt_secret_key() == "real-production-secret"


def test_non_development_missing_secret_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch, environment="staging", jwt_secret=None
    )
    with pytest.raises(TokenError):
        settings.effective_jwt_secret_key()


def test_non_development_blank_secret_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch, environment="staging", jwt_secret="   "
    )
    with pytest.raises(TokenError):
        settings.effective_jwt_secret_key()


def test_hardcoded_dev_secret_never_usable_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch,
        environment="production",
        jwt_secret=_DEV_ONLY_JWT_SECRET,
    )
    with pytest.raises(TokenError):
        settings.effective_jwt_secret_key()


# ---------------------------------------------------------------------------
# Public registration role allow-list
# ---------------------------------------------------------------------------


def test_public_register_role_defaults_to_viewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch, environment="development", jwt_secret=None
    )
    assert settings.public_register_role == "VIEWER"


def test_public_register_role_accepts_viewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _build_settings(
        monkeypatch,
        environment="development",
        jwt_secret=None,
        public_role="VIEWER",
    )
    assert settings.public_register_role == "VIEWER"


@pytest.mark.parametrize("role", ["ADMIN", "REVIEWER", "ASSESSOR", "RESPONDER"])
def test_public_register_role_rejects_privileged(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    with pytest.raises(ValueError):
        _build_settings(
            monkeypatch,
            environment="development",
            jwt_secret=None,
            public_role=role,
        )
