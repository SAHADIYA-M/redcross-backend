"""Phase 12 tests: Response Activities API (/api/responses).

Covers creation, retrieval, listing and filters (report, need, status, source,
time, location), validation errors (invalid report/need/status, empty update),
continuous status updates with identity preservation, and the Phase 9 audit
integration for status changes.
"""

import pytest
from fastapi.testclient import TestClient

from app.audit.schemas import AuditAction
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.api.responses import get_response_repository, get_response_service
from app.api.verification import get_audit_repository, get_verification_service
from app.main import app
from app.repositories import InMemoryReportRepository, InMemoryResponseRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.services.response_service import ResponseService
from app.verification.service import VerificationService

REPORT_BASE = "2026-09-20T08:00:00Z"


@pytest.fixture()
def client(auth_setup, admin_headers):
    """Clean, isolated in-memory storage shared by reports, responses and
    the audit log, wired to the live FastAPI application. The client is
    pre-authenticated as the seeded ADMIN user."""
    report_repository = InMemoryReportRepository()
    response_repository = InMemoryResponseRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()

    app.dependency_overrides[get_report_service] = (
        lambda: ReportService(report_repository)
    )
    app.dependency_overrides[get_priority_service] = (
        lambda: PriorityService(report_repository)
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
    with TestClient(app) as test_client:
        test_client.headers.update(admin_headers)
        yield test_client
    app.dependency_overrides.clear()


def _create_report(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "Fifty families need drinking water after the flood",
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "incident": "Flood",
        "timestamp": REPORT_BASE,
        "source": "FIELD_REPORT",
        "needs": ["WATER"],
        "affected_population": 100,
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_response(client: TestClient, report_id: str, **overrides) -> dict:
    payload = {
        "report_id": report_id,
        "need": "WATER",
        "activity": "Water tanker dispatched",
        "response_status": "PLANNED",
        "timestamp": "2026-09-20T10:00:00Z",
        "location": "kozhikode beach",
        "source": "PARTNER",
        "notes": "Two tankers requested",
        "affected_population": 40,
    }
    payload.update(overrides)
    response = client.post("/api/responses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _list(client: TestClient, params=None) -> list[dict]:
    response = client.get("/api/responses", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- creation


def test_create_response_activity(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    assert created["report_id"] == report["id"]
    assert created["need"] == "WATER"
    assert created["activity"] == "Water tanker dispatched"
    assert created["response_status"] == "PLANNED"
    assert created["timestamp"] == "2026-09-20T10:00:00Z"
    assert created["source"] == "PARTNER"
    assert created["location"] == "kozhikode beach"
    assert created["notes"] == "Two tankers requested"
    assert created["affected_population"] == 40
    assert created["response_id"]


def test_create_response_defaults_status_to_planned_and_timestamp(
    client: TestClient,
) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"], timestamp=None)
    assert created["response_status"] == "PLANNED"
    assert created["timestamp"] is not None


def test_create_response_default_timestamp_is_aware_utc(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"], timestamp=None)
    assert created["timestamp"].endswith("Z") or "+00:00" in created["timestamp"]


# --------------------------------------------------------------- retrieval


def test_get_response_by_id(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    response = client.get(f"/api/responses/{created['response_id']}")
    assert response.status_code == 200
    assert response.json()["response_id"] == created["response_id"]


def test_get_nonexistent_response_404(client: TestClient) -> None:
    response = client.get("/api/responses/does-not-exist")
    assert response.status_code == 404


# ------------------------------------------------------------------- list


def test_list_responses_returns_all_newest_first(client: TestClient) -> None:
    report = _create_report(client)
    first = _create_response(
        client, report["id"], timestamp="2026-09-20T09:00:00Z"
    )
    second = _create_response(
        client, report["id"], timestamp="2026-09-20T11:00:00Z"
    )
    items = _list(client)
    assert [item["response_id"] for item in items] == [
        second["response_id"],
        first["response_id"],
    ]


def test_filter_by_report(client: TestClient) -> None:
    report_a = _create_report(client)
    report_b = _create_report(client, location="old bus stand")
    _create_response(client, report_a["id"])
    b_response = _create_response(client, report_b["id"])
    items = _list(client, {"report_id": report_b["id"]})
    assert [item["response_id"] for item in items] == [b_response["response_id"]]


def test_filter_by_need(client: TestClient) -> None:
    report = _create_report(client)
    water = _create_response(client, report["id"], need="WATER")
    food = _create_response(
        client, report["id"], need="FOOD",
        activity="Food parcels distributed",
    )
    items = _list(client, {"need": "FOOD"})
    assert [item["response_id"] for item in items] == [food["response_id"]]
    assert water["response_id"] not in [i["response_id"] for i in items]


def test_filter_by_status(client: TestClient) -> None:
    report = _create_report(client)
    planned = _create_response(client, report["id"])
    _create_response(client, report["id"], response_status="IN_PROGRESS")
    items = _list(client, {"response_status": "PLANNED"})
    assert [item["response_id"] for item in items] == [planned["response_id"]]


def test_filter_by_source_substring(client: TestClient) -> None:
    report = _create_report(client)
    partner = _create_response(client, report["id"], source="RED_CROSS_PARTNER")
    _create_response(client, report["id"], source="OFFICIAL",
                     activity="Bottled water delivery")
    items = _list(client, {"source": "partner"})
    assert [item["response_id"] for item in items] == [partner["response_id"]]


def test_filter_by_location_substring(client: TestClient) -> None:
    report_a = _create_report(client)
    _create_response(client, report_a["id"], location="kozhikode beach")
    report_b = _create_report(client, location="old bus stand")
    bus = _create_response(client, report_b["id"], location="old bus stand")
    items = _list(client, {"location": "bus stand"})
    assert [item["response_id"] for item in items] == [bus["response_id"]]


def test_filter_by_time_window(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"], timestamp="2026-09-19T10:00:00Z",
                     need=None)
    inside = _create_response(client, report["id"],
                              timestamp="2026-09-20T10:00:00Z")
    items = _list(
        client,
        {
            "start_time": "2026-09-20T00:00:00Z",
            "end_time": "2026-09-20T23:59:59Z",
        },
    )
    assert [item["response_id"] for item in items] == [inside["response_id"]]


def test_inverted_time_window_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/responses",
        params={
            "start_time": "2026-09-21T00:00:00Z",
            "end_time": "2026-09-20T00:00:00Z",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- validation


def test_create_response_invalid_report_404(client: TestClient) -> None:
    response = client.post(
        "/api/responses",
        json={
            "report_id": "no-such-report",
            "activity": "Water tanker dispatched",
        },
    )
    assert response.status_code == 404


def test_create_response_invalid_need_rejected(client: TestClient) -> None:
    report = _create_report(client)
    response = client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "need": "BOGUS",
            "activity": "Water tanker dispatched",
        },
    )
    assert response.status_code == 422


def test_create_response_invalid_status_rejected(client: TestClient) -> None:
    report = _create_report(client)
    response = client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "activity": "Water tanker dispatched",
            "response_status": "MAYBE",
        },
    )
    assert response.status_code == 422


def test_create_response_blank_activity_rejected(client: TestClient) -> None:
    report = _create_report(client)
    response = client.post(
        "/api/responses",
        json={"report_id": report["id"], "activity": "   "},
    )
    assert response.status_code == 422


def test_negative_affected_population_rejected(client: TestClient) -> None:
    report = _create_report(client)
    response = client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "activity": "Water tanker dispatched",
            "affected_population": -5,
        },
    )
    assert response.status_code == 422


# ------------------------------------------------------- multiple responses


def test_multiple_responses_for_one_report(client: TestClient) -> None:
    report = _create_report(client)
    first = _create_response(client, report["id"])
    second = _create_response(
        client, report["id"], activity="Bottled water delivered"
    )
    items = _list(client, {"report_id": report["id"]})
    ids = {item["response_id"] for item in items}
    assert ids == {first["response_id"], second["response_id"]}


# ---------------------------------------------------------- status updates


def test_planned_to_in_progress_preserves_identity(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    response = client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "IN_PROGRESS", "actor_id": "coordinator_1"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["response_id"] == created["response_id"]
    assert updated["report_id"] == report["id"]
    assert updated["response_status"] == "IN_PROGRESS"
    assert updated["activity"] == "Water tanker dispatched"


def test_in_progress_to_completed(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "IN_PROGRESS"},
    )
    completed = client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "COMPLETED"},
    )
    assert completed.status_code == 200
    assert completed.json()["response_status"] == "COMPLETED"


def test_cancel_response(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    response = client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "CANCELLED"},
    )
    assert response.status_code == 200
    assert response.json()["response_status"] == "CANCELLED"


def test_update_nonexistent_response_404(client: TestClient) -> None:
    response = client.patch(
        "/api/responses/do-not-exist",
        json={"response_status": "COMPLETED"},
    )
    assert response.status_code == 404


def test_update_invalid_status_rejected(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    response = client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "DONE"},
    )
    assert response.status_code == 422


def test_update_with_no_changes_rejected(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    response = client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "PLANNED"},
    )
    assert response.status_code == 422


def test_update_reports_and_identity_cannot_be_changed(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"], need="WATER")
    response = client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "COMPLETED", "report_id": "other"},
    )
    assert response.status_code == 200
    assert response.json()["report_id"] == report["id"]


# -------------------------------------------------------------------- audit


def test_status_change_is_audited(client: TestClient, auth_setup) -> None:
    from app.models.user import UserRole

    admin_user = auth_setup.users[UserRole.ADMIN]
    report = _create_report(client)
    created = _create_response(client, report["id"])
    client.patch(
        f"/api/responses/{created['response_id']}",
        json={"response_status": "IN_PROGRESS", "actor_id": "user_7",
              "reason": "team on site"},
    )
    records = client.get("/api/audit").json()
    matches = [
        r for r in records
        if r["action"] == AuditAction.UPDATE_RESPONSE.value
    ]
    assert len(matches) == 1
    entry = matches[0]
    assert entry["report_id"] == report["id"]
    # The authenticated identity is authoritative; a spoofed "user_7" is
    # never recorded (Phase 13).
    assert entry["actor_id"] == admin_user.user_id
    assert entry["reason"] == "team on site"
    assert entry["old_value"]["response_status"] == "PLANNED"
    assert entry["new_value"]["response_status"] == "IN_PROGRESS"


def test_no_audit_record_when_status_unchanged(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    client.patch(
        f"/api/responses/{created['response_id']}",
        json={"notes": "extra notes"},
    )
    records = client.get("/api/audit").json()
    assert not any(
        r["action"] == AuditAction.UPDATE_RESPONSE.value for r in records
    )


# ---------------------------------------------------------------- OpenAPI


def test_responses_endpoints_in_openapi() -> None:
    schema = app.openapi()
    assert "/api/responses" in schema["paths"]
    assert "/api/responses/{response_id}" in schema["paths"]
    # Request/response models are registered as components; the filter model
    # is inlined as query parameters (the established map/search convention).
    schema_names = schema["components"]["schemas"]
    for name in (
        "CreateResponse",
        "UpdateResponse",
        "ResponseActivity",
        "ResponseStatus",
    ):
        assert name in schema_names, name
    status_enum = schema_names["ResponseStatus"]["enum"]
    assert status_enum == ["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]

    list_params = {
        parameter["name"]
        for parameter in schema["paths"]["/api/responses"]["get"]["parameters"]
    }
    for expected in (
        "report_id",
        "need",
        "response_status",
        "source",
        "location",
        "start_time",
        "end_time",
    ):
        assert expected in list_params, expected
    assert schema["paths"]["/api/responses"]["post"]["requestBody"]