"""Batch 4: bounded input payloads on the remaining write paths.

Report/AI payloads were bounded in Batch 3. Batch 4 extends the same
guarantee to response activities, verification reasons/edits and the auth
login/update payloads, all of which write free text (including into the
append-only audit trail) and were previously unbounded. Oversized payloads
are rejected with a normal 422 validation error, never silently truncated.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.lengths import (
    MAX_ACTIVITY_LENGTH,
    MAX_FULL_NAME_LENGTH,
    MAX_LIST_ITEMS,
    MAX_LOCATION_LENGTH,
    MAX_NOTES_LENGTH,
    MAX_PASSWORD_LENGTH,
    MAX_REASON_LENGTH,
    MAX_VULNERABILITY_ITEM_LENGTH,
)


@pytest.fixture(autouse=True)
def offline_fusion():
    """Keep report creation offline (no Supabase) for deterministic tests.

    The production container wires the shared fusion service to the Postgres
    fusion repository; without an override every report creation touches the
    live database. These tests are about payload bounds, so fusion is run
    against an in-memory store instead.
    """
    from app.core.container import get_fusion_service
    from app.main import app
    from app.repositories.fusion_repository import InMemoryFusionRepository
    from app.services.fusion_service import FusionService

    app.dependency_overrides[get_fusion_service] = lambda: FusionService(
        InMemoryFusionRepository()
    )
    yield
    app.dependency_overrides.pop(get_fusion_service, None)


def _create_report(client: TestClient) -> str:
    response = client.post(
        "/api/reports",
        json={"original_text": "people need clean water", "reporter": "team_a"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ----------------------------------------------------------------- response
# activity / notes / source / reason bounds


def test_create_response_activity_too_long_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    response = app_client.post(
        "/api/responses",
        json={
            "report_id": report_id,
            "activity": "x" * (MAX_ACTIVITY_LENGTH + 1),
        },
    )
    assert response.status_code == 422


def test_create_response_notes_too_long_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    response = app_client.post(
        "/api/responses",
        json={
            "report_id": report_id,
            "activity": "Water tanker dispatched",
            "notes": "y" * (MAX_NOTES_LENGTH + 1),
        },
    )
    assert response.status_code == 422


def test_create_response_source_too_long_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    response = app_client.post(
        "/api/responses",
        json={
            "report_id": report_id,
            "activity": "Water tanker dispatched",
            "source": "z" * (MAX_LOCATION_LENGTH + 1),
        },
    )
    assert response.status_code == 422


def test_create_response_at_limit_activity_accepted(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    response = app_client.post(
        "/api/responses",
        json={"report_id": report_id, "activity": "w" * MAX_ACTIVITY_LENGTH},
    )
    assert response.status_code == 201, response.text


def test_update_response_activity_too_long_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    created = app_client.post(
        "/api/responses",
        json={"report_id": report_id, "activity": "Food parcels distributed"},
    )
    assert created.status_code == 201
    response_id = created.json()["response_id"]
    response = app_client.patch(
        f"/api/responses/{response_id}",
        json={"activity": "a" * (MAX_ACTIVITY_LENGTH + 1)},
    )
    assert response.status_code == 422


def test_update_response_notes_too_long_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    created = app_client.post(
        "/api/responses",
        json={"report_id": report_id, "activity": "Food parcels distributed"},
    )
    response_id = created.json()["response_id"]
    response = app_client.patch(
        f"/api/responses/{response_id}",
        json={"notes": "b" * (MAX_NOTES_LENGTH + 1)},
    )
    assert response.status_code == 422


def test_update_response_reason_too_long_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    created = app_client.post(
        "/api/responses",
        json={"report_id": report_id, "activity": "Food parcels distributed"},
    )
    response_id = created.json()["response_id"]
    # A status change is the audited lifecycle event; the reason lands in the
    # append-only audit trail, so it must be bounded.
    response = app_client.patch(
        f"/api/responses/{response_id}",
        json={"response_status": "IN_PROGRESS", "reason": "c" * (MAX_REASON_LENGTH + 1)},
    )
    assert response.status_code == 422


# ----------------------------------------------------------------- verify
# reason / assessment reason / structured edit bounds


def test_verify_reason_too_long_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    response = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "APPROVE", "reason": "r" * (MAX_REASON_LENGTH + 1)},
    )
    assert response.status_code == 422


def test_request_assessment_reason_too_long_rejected(
    app_client: TestClient,
) -> None:
    report_id = _create_report(app_client)
    response = app_client.post(
        f"/api/reports/{report_id}/request-assessment",
        json={"reason": "s" * (MAX_REASON_LENGTH + 1)},
    )
    assert response.status_code == 422


def test_verification_edit_location_too_long_rejected(
    app_client: TestClient,
) -> None:
    report_id = _create_report(app_client)
    response = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "EDIT", "edits": {"location": "L" * (MAX_LOCATION_LENGTH + 1)}},
    )
    assert response.status_code == 422


def test_verification_edit_vulnerability_item_too_long_rejected(
    app_client: TestClient,
) -> None:
    report_id = _create_report(app_client)
    response = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={
            "action": "EDIT",
            "edits": {"vulnerability": ["V" * (MAX_VULNERABILITY_ITEM_LENGTH + 1)]},
        },
    )
    assert response.status_code == 422


def test_verification_edit_needs_too_many_rejected(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    response = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={
            "action": "EDIT",
            "edits": {"needs": ["WATER"] * (MAX_LIST_ITEMS + 1)},
        },
    )
    assert response.status_code == 422


def test_verification_edit_within_limit_applied(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    response = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "EDIT", "edits": {"incident": "Flooding near the bridge"}},
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------------------------ auth
# login password / user full_name bounds


def test_login_password_too_long_rejected(auth_setup) -> None:
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={"username": "admin_user", "password": "p" * (MAX_PASSWORD_LENGTH + 1)},
        )
        assert response.status_code == 422
    app.dependency_overrides.clear()


def test_user_update_full_name_too_long_rejected(
    app_client: TestClient, auth_setup
) -> None:
    from app.models.user import UserRole

    admin_id = auth_setup.users[UserRole.ADMIN].user_id
    response = app_client.patch(
        f"/api/users/{admin_id}",
        json={"full_name": "n" * (MAX_FULL_NAME_LENGTH + 1)},
    )
    assert response.status_code == 422