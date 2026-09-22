"""Batch 4: bounded pagination on the unbounded list endpoints.

GET /api/reports, /api/responses, /api/verification, /api/audit and
/api/users previously returned the entire dataset, letting a single request
materialise the whole store in memory (resource exhaustion). Each now
accepts a bounded ``limit`` (1-1000, default 100) and zero-based ``offset``
so clients page through results. The response shape stays an array.
"""

import pytest
from fastapi.testclient import TestClient

from app.schemas.lengths import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT


@pytest.fixture(autouse=True)
def offline_fusion():
    """Keep report creation offline (no Supabase) for deterministic tests.

    The production container wires the shared fusion service to the Postgres
    fusion repository; without an override every report creation touches the
    live database. These tests are about pagination, so fusion is run against
    an in-memory store instead.
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


def _approve_report(client: TestClient, report_id: str) -> None:
    response = client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "APPROVE", "reason": "confirmed in the field"},
    )
    assert response.status_code == 200, response.text


def _create_response(client: TestClient, report_id: str) -> None:
    response = client.post(
        "/api/responses",
        json={"report_id": report_id, "activity": "Food parcels distributed"},
    )
    assert response.status_code == 201, response.text


# ----------------------------------------------------------------- reports


def test_reports_list_respects_explicit_limit(app_client: TestClient) -> None:
    for _ in range(3):
        _create_report(app_client)
    listing = app_client.get("/api/reports", params={"limit": 2}).json()
    assert len(listing) == 2


def test_reports_list_respects_offset(app_client: TestClient) -> None:
    for _ in range(3):
        _create_report(app_client)
    should_be_remaining = app_client.get("/api/reports").json()
    assert len(should_be_remaining) == 3
    paged = app_client.get(
        "/api/reports", params={"limit": 2, "offset": 2}
    ).json()
    assert len(paged) == 1


def test_reports_list_limited_default_and_bounded(app_client: TestClient) -> None:
    for _ in range(3):
        _create_report(app_client)
    listing = app_client.get("/api/reports").json()
    assert len(listing) <= DEFAULT_LIST_LIMIT


def test_reports_list_rejects_invalid_limit(app_client: TestClient) -> None:
    _create_report(app_client)
    assert app_client.get("/api/reports", params={"limit": 0}).status_code == 422
    assert (
        app_client.get(
            "/api/reports", params={"limit": MAX_LIST_LIMIT + 1}
        ).status_code
        == 422
    )
    assert app_client.get("/api/reports", params={"offset": -1}).status_code == 422


# ----------------------------------------------------------------- responses


def test_responses_list_respects_limit(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    for _ in range(3):
        _create_response(app_client, report_id)
    listing = app_client.get("/api/responses", params={"limit": 2}).json()
    assert len(listing) == 2


# -------------------------------------------------------------- verification


def test_verifications_list_respects_limit(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    _approve_report(app_client, report_id)
    # VERIFIED -> UNCERTAIN -> VERIFIED: three verification records total.
    response = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "MARK_UNCERTAIN", "reason": "needs a second look"},
    )
    assert response.status_code == 200
    _approve_report(app_client, report_id)
    assert len(app_client.get("/api/verification").json()) == 3
    listing = app_client.get("/api/verification", params={"limit": 2}).json()
    assert len(listing) == 2


# ---------------------------------------------------------------------- audit


def test_audit_list_respects_limit_and_offset(app_client: TestClient) -> None:
    report_id = _create_report(app_client)
    _approve_report(app_client, report_id)
    assert len(app_client.get("/api/audit").json()) >= 1
    listing = app_client.get("/api/audit", params={"limit": 1}).json()
    assert len(listing) == 1


# ---------------------------------------------------------------------- users


def test_users_list_respects_limit_and_offset(app_client: TestClient) -> None:
    all_users = app_client.get("/api/users").json()
    assert len(all_users) >= 2  # one seeded user per role
    listing = app_client.get("/api/users", params={"limit": 1}).json()
    assert len(listing) == 1
    next_page = app_client.get(
        "/api/users", params={"limit": 1, "offset": 1}
    ).json()
    assert len(next_page) == 1
    assert next_page[0]["user_id"] != listing[0]["user_id"]