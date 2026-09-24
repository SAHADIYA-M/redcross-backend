import pytest
from fastapi.testclient import TestClient

from app.api.conflicts import get_conflict_service
from app.api.reports import get_report_service
from app.conflicts.service import ConflictDetectionService
from app.main import app
from app.repositories import InMemoryReportRepository
from app.services.report_service import ReportService

BASE_TIME = "2026-09-18T10:00:00Z"


@pytest.fixture()
def client():
    """Share ONE repository between report creation and conflict detection."""
    repository = InMemoryReportRepository()
    app.dependency_overrides[get_report_service] = lambda: ReportService(repository)
    app.dependency_overrides[get_conflict_service] = (
        lambda: ConflictDetectionService(repository)
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "500 families need clean drinking water after the flood",
        "reporter": "field_team_01",
        "location": "Riverside Camp",
        "incident": "Flood",
        "timestamp": BASE_TIME,
        "source": "FIELD_REPORT",
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _detect(client: TestClient, report_id: str) -> dict:
    response = client.post(f"/api/reports/{report_id}/conflicts")
    assert response.status_code == 200, response.text
    return response.json()


def _find_conflict(payload: dict, related_id: str) -> dict | None:
    return next(
        (
            p
            for p in payload["potential_conflicts"]
            if p["related_report_id"] == related_id
        ),
        None,
    )


def test_contradictory_affected_population(client: TestClient) -> None:
    report_a = _create(client, affected_population=20)
    report_b = _create(client, affected_population=3)
    result = _detect(client, report_a["id"])
    conflict = _find_conflict(result, report_b["id"])
    assert conflict is not None
    assert conflict["relation"] == "POTENTIAL_CONFLICT"
    claim = next(c for c in conflict["conflicts"] if c["field"] == "affected_population")
    assert claim["report_a_value"] == 20
    assert claim["report_b_value"] == 3
    assert claim["reason"]


def test_similar_affected_population_is_not_a_conflict(client: TestClient) -> None:
    report_a = _create(client, affected_population=20)
    report_b = _create(client, affected_population=22)
    result = _detect(client, report_a["id"])
    assert _find_conflict(result, report_b["id"]) is None


def test_contradictory_severity(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH")
    report_b = _create(client, severity="LOW")
    result = _detect(client, report_a["id"])
    conflict = _find_conflict(result, report_b["id"])
    assert conflict is not None
    claim = next(c for c in conflict["conflicts"] if c["field"] == "severity")
    assert claim["report_a_value"] == "HIGH"
    assert claim["report_b_value"] == "LOW"


def test_contradictory_infrastructure_status(client: TestClient) -> None:
    report_a = _create(client, infrastructure_status="DESTROYED")
    report_b = _create(client, infrastructure_status="DAMAGED")
    result = _detect(client, report_a["id"])
    conflict = _find_conflict(result, report_b["id"])
    assert conflict is not None
    claim = next(
        c for c in conflict["conflicts"] if c["field"] == "infrastructure_status"
    )
    assert claim["report_a_value"] == "DESTROYED"
    assert claim["report_b_value"] == "DAMAGED"


def test_contradictory_need_availability(client: TestClient) -> None:
    report_a = _create(client, needs=["WATER"])
    report_b = _create(client, available_needs=["WATER"])
    result = _detect(client, report_a["id"])
    conflict = _find_conflict(result, report_b["id"])
    assert conflict is not None
    claim = next(c for c in conflict["conflicts"] if c["field"].startswith("need."))
    assert "NEEDED" in claim["report_a_value"]
    assert "AVAILABLE" in claim["report_b_value"]


def test_same_incident_different_wording_not_a_conflict(client: TestClient) -> None:
    report_a = _create(
        client,
        original_text="Flooding has damaged homes near the river",
        severity="HIGH",
    )
    report_b = _create(
        client,
        original_text="Several houses near the river are flooded",
        severity="HIGH",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_conflicts"] == []


def test_different_incidents_similar_wording_not_a_conflict(client: TestClient) -> None:
    report_a = _create(
        client,
        original_text="Flooding has damaged homes in Village A",
        location="Village A",
        severity="HIGH",
    )
    report_b = _create(
        client,
        original_text="Flooding has damaged homes in Village B",
        location="Village B",
        severity="LOW",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_conflicts"] == []


def test_missing_value_vs_actual_value_not_a_conflict(client: TestClient) -> None:
    report_a = _create(client, affected_population=20)
    report_b = _create(client)  # affected_population missing
    result = _detect(client, report_a["id"])
    assert _find_conflict(result, report_b["id"]) is None


def test_unknown_vs_known_value_not_a_conflict(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH")
    report_b = _create(client)  # severity unknown
    result = _detect(client, report_a["id"])
    assert _find_conflict(result, report_b["id"]) is None


def test_uncertain_location_handled_safely(client: TestClient) -> None:
    report_a = _create(
        client,
        location="somewhere north",
        location_status="UNCERTAIN",
        severity="HIGH",
    )
    report_b = _create(
        client,
        location="Riverside",
        location_status="CONFIRMED",
        severity="LOW",
    )
    result = _detect(client, report_a["id"])
    conflict = _find_conflict(result, report_b["id"])
    assert conflict is not None
    assert any(c["field"] == "severity" for c in conflict["conflicts"])


def test_different_locations_not_compared(client: TestClient) -> None:
    report_a = _create(client, location="Village A", severity="HIGH")
    report_b = _create(client, location="Village B", severity="LOW")
    result = _detect(client, report_a["id"])
    assert result["potential_conflicts"] == []


def test_unrelated_reports_not_compared(client: TestClient) -> None:
    report_a = _create(
        client,
        original_text="Flooding damaged riverside homes",
        location="Riverside Camp",
        incident="Flood",
        severity="HIGH",
    )
    report_b = _create(
        client,
        original_text="An earthquake destroyed mountain village schools",
        location="Mountain Village",
        incident="Earthquake",
        timestamp="2026-10-01T08:00:00Z",
        severity="LOW",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_conflicts"] == []


def test_report_not_compared_with_itself(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH")
    result = _detect(client, report_a["id"])
    assert result["potential_conflicts"] == []
    assert all(
        p["related_report_id"] != report_a["id"]
        for p in result["potential_conflicts"]
    )


def test_nonexistent_report_returns_404(client: TestClient) -> None:
    response = client.post("/api/reports/does-not-exist/conflicts")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_multiple_conflicts_between_two_reports(client: TestClient) -> None:
    report_a = _create(
        client, affected_population=20, severity="HIGH", infrastructure_status="DESTROYED"
    )
    report_b = _create(
        client, affected_population=3, severity="LOW", infrastructure_status="DAMAGED"
    )
    result = _detect(client, report_a["id"])
    conflict = _find_conflict(result, report_b["id"])
    assert conflict is not None
    fields = {c["field"] for c in conflict["conflicts"]}
    assert {"affected_population", "severity", "infrastructure_status"} <= fields


def test_multiple_conflicting_reports(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH")
    report_b = _create(client, severity="LOW")
    report_c = _create(client, severity="CRITICAL")
    result = _detect(client, report_a["id"])
    related = {p["related_report_id"] for p in result["potential_conflicts"]}
    assert report_b["id"] in related
    assert report_c["id"] in related


def test_potential_conflict_relationship_returned(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH")
    report_b = _create(client, severity="LOW")
    result = _detect(client, report_a["id"])
    assert result["report_id"] == report_a["id"]
    conflict = _find_conflict(result, report_b["id"])
    assert conflict["relation"] == "POTENTIAL_CONFLICT"
    assert conflict["conflicts"]


def test_original_reports_remain_unchanged(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH", affected_population=20)
    report_b = _create(client, severity="LOW", affected_population=3)
    _detect(client, report_a["id"])
    after_a = client.get(f"/api/reports/{report_a['id']}").json()
    after_b = client.get(f"/api/reports/{report_b['id']}").json()
    assert after_a == report_a
    assert after_b == report_b
    assert after_a["original_text"] == report_a["original_text"]


def test_no_automatic_resolution(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH", status="RECEIVED")
    report_b = _create(client, severity="LOW", status="RECEIVED")
    _detect(client, report_a["id"])
    assert client.get(f"/api/reports/{report_a['id']}").json()["status"] == "RECEIVED"
    assert client.get(f"/api/reports/{report_b['id']}").json()["status"] == "RECEIVED"


def test_no_automatic_merge(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH")
    report_b = _create(client, severity="LOW")
    _detect(client, report_a["id"])
    all_reports = client.get("/api/reports").json()
    ids = {r["id"] for r in all_reports}
    assert report_a["id"] in ids
    assert report_b["id"] in ids
    assert len(all_reports) == 2


def test_no_automatic_deletion(client: TestClient) -> None:
    report_a = _create(client, severity="HIGH")
    report_b = _create(client, severity="LOW")
    _detect(client, report_a["id"])
    assert client.get(f"/api/reports/{report_a['id']}").status_code == 200
    assert client.get(f"/api/reports/{report_b['id']}").status_code == 200


def test_endpoint_is_registered_in_openapi(client: TestClient) -> None:
    paths = app.openapi()["paths"]
    assert "/api/reports/{report_id}/conflicts" in paths