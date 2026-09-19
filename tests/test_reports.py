import pytest
from fastapi.testclient import TestClient

from app.api.reports import get_report_service
from app.main import app
from app.repositories import InMemoryReportRepository
from app.services.report_service import ReportService


@pytest.fixture()
def client():
    """Give every test a clean, isolated in-memory repository."""
    repository = InMemoryReportRepository()
    service = ReportService(repository)
    app.dependency_overrides[get_report_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_report(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "500 families need clean drinking water",
        "reporter": "field_team_01",
        "location": "Area X",
        "incident": "Flood",
        "source": "FIELD_REPORT",
    }
    payload.update(overrides)
    return client.post("/api/reports", json=payload).json()


def test_create_report(client: TestClient) -> None:
    response = client.post(
        "/api/reports",
        json={
            "original_text": "500 families need clean drinking water",
            "reporter": "field_team_01",
            "location": "Area X",
            "incident": "Flood",
            "source": "FIELD_REPORT",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["original_text"] == "500 families need clean drinking water"
    assert body["status"] == "RECEIVED"
    assert body["timestamp"]


def test_get_all_reports(client: TestClient) -> None:
    _create_report(client, original_text="First")
    _create_report(client, original_text="Second")
    response = client.get("/api/reports")
    assert response.status_code == 200
    reports = response.json()
    assert len(reports) == 2
    assert {r["original_text"] for r in reports} == {"First", "Second"}


def test_get_report_by_id(client: TestClient) -> None:
    created = _create_report(client)
    response = client.get(f"/api/reports/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_nonexistent_report(client: TestClient) -> None:
    response = client.get("/api/reports/does-not-exist")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_update_report_preserves_original_text(client: TestClient) -> None:
    created = _create_report(client)
    response = client.patch(
        f"/api/reports/{created['id']}",
        json={"status": "IN_REVIEW"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "IN_REVIEW"
    assert body["original_text"] == created["original_text"]


def test_update_nonexistent_report(client: TestClient) -> None:
    response = client.patch(
        "/api/reports/does-not-exist",
        json={"status": "RESOLVED"},
    )
    assert response.status_code == 404


def test_create_report_validation_failure(client: TestClient) -> None:
    response = client.post("/api/reports", json={"original_text": "no reporter"})
    assert response.status_code == 422