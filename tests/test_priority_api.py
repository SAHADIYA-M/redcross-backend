import pytest
from fastapi.testclient import TestClient

from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.main import app
from app.repositories import InMemoryReportRepository
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService

BASE_TIME = "2026-09-20T10:00:00Z"


@pytest.fixture()
def client(auth_setup, admin_headers):
    """Share ONE repository between report creation and priority calculation."""
    repository = InMemoryReportRepository()
    app.dependency_overrides[get_report_service] = lambda: ReportService(repository)
    app.dependency_overrides[get_priority_service] = (
        lambda: PriorityService(repository)
    )
    with TestClient(app) as test_client:
        test_client.headers.update(admin_headers)
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


def _priority(client: TestClient, report_id: str) -> dict:
    response = client.post(f"/api/reports/{report_id}/priority")
    assert response.status_code == 200, response.text
    return response.json()


def test_priority_success(client: TestClient) -> None:
    report = _create(
        client,
        severity="HIGH",
        affected_population=500,
        vulnerability=["children", "elderly"],
        time_sensitivity="within 24 hours",
        evidence=["no clean water"],
    )
    result = _priority(client, report["id"])
    assert result["report_id"] == report["id"]
    assert result["severity_score"] == 75.0
    assert result["affected_population_score"] == 75.0
    assert result["vulnerability_score"] == 80.0
    assert result["time_sensitivity_score"] == 85.0
    assert result["evidence_verification_score"] == 40.0
    assert result["final_score"] == 74.0
    assert result["priority_level"] == "HIGH"
    assert result["calculation_version"] == "1"
    assert "calculated_at" in result
    assert result["explanations"]["severity"]
    assert result["source_values"]["affected_population"] == 500


def test_priority_nonexistent_report_returns_404(client: TestClient) -> None:
    response = client.post("/api/reports/nope/priority")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_priority_without_usable_information_returns_422(client: TestClient) -> None:
    report = _create(client)
    response = client.post(f"/api/reports/{report['id']}/priority")
    assert response.status_code == 422
    assert "no usable priority information" in response.json()["detail"]


def test_invalid_severity_enum_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/reports",
        json={
            "original_text": "bad severity",
            "reporter": "team",
            "severity": "BOGUS",
        },
    )
    assert response.status_code == 422


def test_negative_population_rejected_at_creation(client: TestClient) -> None:
    response = client.post(
        "/api/reports",
        json={
            "original_text": "negative population",
            "reporter": "team",
            "affected_population": -5,
        },
    )
    assert response.status_code == 422


def test_original_report_data_remains_unchanged(client: TestClient) -> None:
    report = _create(
        client,
        severity="CRITICAL",
        affected_population=2000,
        evidence=["quote one", "quote two", "quote three"],
    )
    _priority(client, report["id"])
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["original_text"] == report["original_text"]
    assert stored["location"] == report["location"]
    assert stored["incident"] == report["incident"]
    assert stored["severity"] == "CRITICAL"
    assert stored["affected_population"] == 2000
    assert stored["reporter"] == report["reporter"]


def test_report_text_cannot_override_backend_score(client: TestClient) -> None:
    claims = {
        "severity": "MEDIUM",
        "affected_population": 300,
        "vulnerability": ["children"],
        "time_sensitivity": "soon",
        "evidence": ["water is contaminated"],
    }
    loud = _create(
        client,
        original_text="CRITICAL URGENT VITAL EMERGENCY across the whole region NOW",
        **claims,
    )
    quiet = _create(
        client,
        original_text="minor situation, low priority, not urgent",
        **claims,
    )
    loud_result = _priority(client, loud["id"])
    quiet_result = _priority(client, quiet["id"])
    assert loud_result["priority_level"] == quiet_result["priority_level"]
    assert loud_result["final_score"] == quiet_result["final_score"]


def test_priority_calculation_is_deterministic(client: TestClient) -> None:
    report = _create(client, severity="HIGH", affected_population=500)
    first = _priority(client, report["id"])
    second = _priority(client, report["id"])
    assert first["final_score"] == second["final_score"]
    assert first["priority_level"] == second["priority_level"]


def test_scores_are_within_range(client: TestClient) -> None:
    report = _create(client, severity="CRITICAL")
    result = _priority(client, report["id"])
    factor_fields = (
        "severity_score",
        "affected_population_score",
        "vulnerability_score",
        "time_sensitivity_score",
        "evidence_verification_score",
        "final_score",
    )
    for field in factor_fields:
        assert 0 <= result[field] <= 100, field


def test_endpoint_registered_in_openapi(client: TestClient) -> None:
    schema = app.openapi()
    assert "/api/reports/{report_id}/priority" in schema["paths"]
    assert "post" in schema["paths"]["/api/reports/{report_id}/priority"]