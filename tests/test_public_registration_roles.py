"""Batch 1 public-registration privilege-escalation tests.

Public registration must only ever produce the allow-listed public role
(VIEWER). Supplying a role in the body is rejected, and even a misconfigured
public role can never grant a privileged role through the auth service.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.user import UserRole
from app.repositories import InMemoryUserRepository
from app.schemas.auth import UserCreate
from app.services.auth_service import AuthService


def _register(client: TestClient, username: str, **extra) -> object:
    payload = {"username": username, "password": "supersecret1"}
    payload.update(extra)
    return client.post("/api/auth/register", json=payload)


def test_normal_registration_creates_public_role(auth_setup) -> None:
    with TestClient(app) as client:
        response = _register(client, "normal_user")
        assert response.status_code == 201, response.text
        assert response.json()["role"] == UserRole.VIEWER.value


@pytest.mark.parametrize(
    "role",
    ["ADMIN", "REVIEWER", "ASSESSOR", "RESPONDER"],
)
def test_role_in_body_is_rejected(auth_setup, role: str) -> None:
    with TestClient(app) as client:
        response = _register(client, f"hacker_{role.lower()}", role=role)
        # ``extra="forbid"`` on UserCreate means a role field is rejected
        # outright, so escalation is impossible by design.
        assert response.status_code == 422


def test_client_cannot_self_register_into_privileged_role(auth_setup) -> None:
    with TestClient(app) as client:
        _register(client, "escalator", role="ADMIN")
    stored = auth_setup.service.get_by_username("escalator")
    assert stored is None  # the rejected request created nothing


def test_misconfigured_public_role_is_clamped_to_viewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "public_register_role", "REVIEWER")
    service = AuthService(InMemoryUserRepository())
    user = service.register(
        UserCreate(username="sneaky_reviewer", password="supersecret1")
    )
    assert user.role == UserRole.VIEWER


def test_registration_then_login_still_works(auth_setup) -> None:
    with TestClient(app) as client:
        assert _register(client, "login_after_register").status_code == 201
        response = client.post(
            "/api/auth/login",
            json={
                "username": "login_after_register",
                "password": "supersecret1",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user"]["role"] == UserRole.VIEWER.value
