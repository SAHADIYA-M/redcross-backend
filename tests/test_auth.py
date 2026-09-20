"""Phase 13 Authentication & Authorization tests.

Covers:
- AUTHENTICATION: registration, duplicate handling, hashed-storage, login,
  token issuance, identity round trip, expired/invalid/missing tokens,
  public health endpoints, inactive accounts.
- AUTHORIZATION: role boundaries (VIEWER read-only, REVIEWER verify,
  RESPONDER mutate responses, ADMIN user management), no self-escalation,
  no reviewer/actor spoofing.
- AUDIT: identity recorded authoritatively; auth required.
- REGRESSION: the Phase 1-12 report flow still works under auth and the
  client-supplied ``reporter`` field is preserved (auth identity is the API
  actor, not the report author attribute).
"""

import pytest
from fastapi.testclient import TestClient

from app.api.reports import get_report_service
from app.api.responses import get_response_repository, get_response_service
from app.api.verification import get_audit_repository, get_verification_service
from app.audit.schemas import AuditAction
from app.core.security import create_access_token, verify_password
from app.main import app
from app.models.user import UserRole
from app.repositories.in_memory_audit_repository import (
    InMemoryAuditRepository,
)
from app.repositories.in_memory_report_repository import (
    InMemoryReportRepository,
)
from app.repositories.in_memory_response_repository import (
    InMemoryResponseRepository,
)
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.schemas.auth import UserUpdate
from app.services.report_service import ReportService
from app.services.response_service import ResponseService
from app.verification.service import VerificationService

from tests.helpers import DEV_PASSWORD, attach_auth, headers_for


def _register(client: TestClient, username: str, password: str = "supersecret1", **extra):
    payload = {"username": username, "password": password}
    payload.update(extra)
    return client.post("/api/auth/register", json=payload)


def _report_payload(**overrides) -> dict:
    payload = {
        "original_text": "Families need clean drinking water after the flood",
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "incident": "Flood",
        "timestamp": "2026-09-20T08:00:00Z",
        "source": "FIELD_REPORT",
        "needs": ["WATER"],
    }
    payload.update(overrides)
    return payload


def _create_report(client: TestClient, **overrides) -> dict:
    response = client.post("/api/reports", json=_report_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _create_response(client: TestClient, report_id: str, **overrides) -> dict:
    payload = {
        "report_id": report_id,
        "need": "WATER",
        "activity": "Water tanker dispatched",
        "response_status": "PLANNED",
    }
    payload.update(overrides)
    response = client.post("/api/responses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def role_client(auth_setup):
    """Wire shared report/verification/audit/response storage and return a
    client factory authenticating as any seeded role."""
    report_repository = InMemoryReportRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()
    response_repository = InMemoryResponseRepository()

    app.dependency_overrides[get_report_service] = (
        lambda: ReportService(report_repository)
    )
    app.dependency_overrides[get_verification_service] = (
        lambda: VerificationService(
            report_repository,
            verification_repository,
            audit_repository,
        )
    )
    app.dependency_overrides[get_audit_repository] = lambda: audit_repository
    app.dependency_overrides[get_response_repository] = (
        lambda: response_repository
    )
    app.dependency_overrides[get_response_service] = (
        lambda: ResponseService(
            response_repository,
            report_repository,
            audit_repository,
        )
    )

    def _make(role: UserRole) -> TestClient:
        client = TestClient(app)
        return attach_auth(client, auth_setup, role)

    yield _make
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------------------

def test_public_registration_creates_viewer(auth_setup) -> None:
    with TestClient(app) as client:
        response = _register(client, "newfielduser", full_name="New Field User")
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["username"] == "newfielduser"
        assert body["role"] == UserRole.VIEWER.value
        assert body["is_active"] is True
        assert body["full_name"] == "New Field User"
        assert body["user_id"]
        assert body["created_at"]
        assert "password" not in body
        assert "password_hash" not in body


def test_register_duplicate_username_is_conflict(auth_setup) -> None:
    with TestClient(app) as client:
        _register(client, "freshuser")
        assert _register(client, "freshuser").status_code == 409
        # Username lookup is case-insensitive: same account either way.
        assert _register(client, "FRESHUSER").status_code == 409


def test_password_is_stored_hashed(auth_setup) -> None:
    with TestClient(app) as client:
        _register(client, "hashme", password="Battery-Staple-9")
        stored = auth_setup.service.get_by_username("hashme")
        assert stored is not None
        assert stored.password_hash != "Battery-Staple-9"
        assert "Battery-Staple-9" not in stored.password_hash
        assert verify_password("Battery-Staple-9", stored.password_hash)
        assert not verify_password("wrong", stored.password_hash)


def test_login_returns_token_and_user(auth_setup) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin_user", "password": DEV_PASSWORD},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        user = body["user"]
        assert user["username"] == "admin_user"
        assert user["role"] == UserRole.ADMIN.value
        # The token resolves back to the same identity.
        me = TestClient(app)
        me.headers.update(
            {"Authorization": f"Bearer {body['access_token']}"}
        )
        me_response = me.get("/api/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["username"] == "admin_user"


def test_login_wrong_password_is_generic_401(auth_setup) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin_user", "password": "wrong-pass-1"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"


def test_login_unknown_user_is_generic_401(auth_setup) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "whatever-1"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"


def test_me_returns_authenticated_user(auth_setup) -> None:
    with TestClient(app) as client:
        headers = headers_for(auth_setup, UserRole.REVIEWER)
        response = client.get("/api/auth/me", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["username"] == "reviewer_user"
        assert body["role"] == UserRole.REVIEWER.value


def test_me_requires_token(auth_setup) -> None:
    with TestClient(app) as client:
        assert client.get("/api/auth/me").status_code == 401


def test_expired_token_is_rejected(auth_setup) -> None:
    viewer = auth_setup.users[UserRole.VIEWER]
    token = create_access_token(
        subject=viewer.user_id,
        role=viewer.role.value,
        expires_minutes=-5,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/reports",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or expired token"


def test_invalid_token_is_rejected(auth_setup) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/reports",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert response.status_code == 401


def test_missing_token_on_protected_endpoint_is_rejected(auth_setup) -> None:
    with TestClient(app) as client:
        assert client.get("/api/reports").status_code == 401
        assert client.post(
            "/api/reports", json=_report_payload()
        ).status_code == 401


def test_health_endpoints_are_public(auth_setup) -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200


# ---------------------------------------------------------------------------
# AUTHORIZATION
# ---------------------------------------------------------------------------

def test_registration_cannot_self_assign_role(auth_setup) -> None:
    with TestClient(app) as client:
        # A role field is rejected outright (extra="forbid"): escalation is
        # impossible through registration.
        response = _register(client, "hacker", role="ADMIN")
        assert response.status_code == 422


def test_viewer_cannot_create_report(role_client) -> None:
    client = role_client(UserRole.VIEWER)
    response = client.post("/api/reports", json=_report_payload())
    assert response.status_code == 403


def test_admin_can_create_report(role_client) -> None:
    client = role_client(UserRole.ADMIN)
    assert client.post("/api/reports", json=_report_payload()).status_code == 201


def test_viewer_can_read_reports(role_client) -> None:
    client = role_client(UserRole.VIEWER)
    response = client.get("/api/reports")
    assert response.status_code == 200


def test_viewer_cannot_verify_report(role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    report = _create_report(admin)
    viewer = role_client(UserRole.VIEWER)
    response = viewer.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "confirmed"},
    )
    assert response.status_code == 403


def test_reviewer_can_verify_report(role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    report = _create_report(admin)
    reviewer = role_client(UserRole.REVIEWER)
    response = reviewer.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "field-confirmed"},
    )
    assert response.status_code == 200
    assert response.json()["report"]["verification_status"] == "VERIFIED"


def test_viewer_cannot_modify_response(role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    report = _create_report(admin)
    created = _create_response(admin, report["id"])
    viewer = role_client(UserRole.VIEWER)
    response = viewer.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "IN_PROGRESS"},
    )
    assert response.status_code == 403


def test_responder_can_update_response(role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    report = _create_report(admin)
    created = _create_response(admin, report["id"])
    responder = role_client(UserRole.RESPONDER)
    response = responder.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "IN_PROGRESS", "reason": "team on site"},
    )
    assert response.status_code == 200
    assert response.json()["response_status"] == "IN_PROGRESS"


def test_viewer_cannot_list_users(role_client) -> None:
    client = role_client(UserRole.VIEWER)
    assert client.get("/api/users").status_code == 403


def test_admin_can_list_users(role_client) -> None:
    client = role_client(UserRole.ADMIN)
    response = client.get("/api/users")
    assert response.status_code == 200
    names = [u["username"] for u in response.json()]
    assert "admin_user" in names
    assert "viewer_user" in names


def test_inactive_user_is_forbidden(auth_setup, role_client) -> None:
    viewer = auth_setup.users[UserRole.VIEWER]
    auth_setup.service.update_user(viewer.user_id, UserUpdate(is_active=False))
    client = role_client(UserRole.VIEWER)
    response = client.get("/api/reports")
    assert response.status_code == 403
    assert response.json()["detail"] == "Inactive user"


def test_cannot_spoof_reviewer_identity(auth_setup, role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    report = _create_report(admin)
    reviewer = role_client(UserRole.REVIEWER)
    response = reviewer.post(
        f"/api/reports/{report['id']}/request-assessment",
        json={
            "reason": "verify in the field",
            "reviewer_id": "santa-claus",
        },
    )
    assert response.status_code == 200
    verification = response.json()["verification"]
    reviewer_user = auth_setup.users[UserRole.REVIEWER]
    assert verification["reviewer_id"] == reviewer_user.user_id
    assert verification["reviewer_id"] != "santa-claus"


def test_wrong_role_cannot_access_admin_user_management(role_client) -> None:
    client = role_client(UserRole.ASSESSOR)
    response = client.get("/api/users")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# AUDIT
# ---------------------------------------------------------------------------

def test_audit_records_authenticated_reviewer(auth_setup, role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    report = _create_report(admin)
    reviewer = role_client(UserRole.REVIEWER)
    reviewer.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "verified on site"},
    )
    records = admin.get("/api/audit").json()
    matches = [
        r for r in records
        if r["action"] == AuditAction.APPROVE.value
    ]
    reviewer_user = auth_setup.users[UserRole.REVIEWER]
    assert matches
    assert matches[0]["actor_id"] == reviewer_user.user_id
    assert matches[0]["report_id"] == report["id"]


def test_audit_requires_authentication(auth_setup, role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    _create_report(admin)
    with TestClient(app) as client:
        assert client.get("/api/audit").status_code == 401


def test_verification_history_requires_authentication(auth_setup, role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    _create_report(admin)
    with TestClient(app) as client:
        assert client.get("/api/verification").status_code == 401


# ---------------------------------------------------------------------------
# REGRESSION
# ---------------------------------------------------------------------------

def test_authenticated_report_flow_still_works(role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    created = _create_report(admin)
    listed = admin.get("/api/reports").json()
    assert any(r["id"] == created["id"] for r in listed)
    fetched = admin.get(f"/api/reports/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["original_text"] == created["original_text"]


def test_reporter_field_from_body_is_preserved(role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    created = _create_report(admin)
    assert created["reporter"] == "field_team_01"


def test_priority_endpoint_requires_authentication(auth_setup, role_client) -> None:
    admin = role_client(UserRole.ADMIN)
    report = _create_report(admin)
    with TestClient(app) as client:
        assert client.post(
            f"/api/reports/{report['id']}/priority"
        ).status_code == 401