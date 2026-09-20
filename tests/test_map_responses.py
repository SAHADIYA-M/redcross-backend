"""Phase 12 tests: map projection for response activities (GET /api/map/responses).

Covers the same coordinate rules as the Phase 11 report map (only CONFIRMED,
in-range, non-0,0 coordinates place an activity), privacy-safe output, filters
and OpenAPI registration.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.map_responses import get_response_map_service
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.api.responses import get_response_repository, get_response_service
from app.api.verification import get_audit_repository, get_verification_service
from app.location.providers import StubGeocoder
from app.location.schemas import GeocodeMatch
from app.location.service import LocationService
from app.main import app
from app.repositories import InMemoryReportRepository, InMemoryResponseRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.services.map_service import is_null_island
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.services.response_map_service import ResponseMapService
from app.services.response_service import ResponseService
from app.verification.service import VerificationService

SENSITIVE_KEYS = {"notes", "affected_population"}


@pytest.fixture()
def client(auth_setup, admin_headers):
    report_repository = InMemoryReportRepository()
    response_repository = InMemoryResponseRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()
    location_service = LocationService(StubGeocoder())

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
    app.dependency_overrides[get_response_map_service] = (
        lambda: ResponseMapService(response_repository, location_service)
    )
    with TestClient(app) as test_client:
        test_client.headers.update(admin_headers)
        yield test_client
    app.dependency_overrides.clear()


def _create_report(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "People need food after the flood",
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "incident": "Flood",
        "timestamp": "2026-09-20T08:00:00Z",
        "source": "FIELD_REPORT",
        "needs": ["FOOD"],
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_response(client: TestClient, report_id: str, **overrides) -> dict:
    payload = {
        "report_id": report_id,
        "need": "FOOD",
        "activity": "Food parcels distributed",
        "response_status": "COMPLETED",
        "timestamp": "2026-09-20T10:00:00Z",
        "location": "kozhikode beach",
        "source": "PARTNER",
        "notes": "operational detail",
        "affected_population": 60,
    }
    payload.update(overrides)
    response = client.post("/api/responses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _map(client: TestClient, params=None) -> dict:
    response = client.get("/api/map/responses", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _by_id(result: dict) -> dict[str, dict]:
    return {item["response_id"]: item for item in result["items"]}


def _single(client: TestClient, response_id: str) -> dict:
    result = _map(client)
    assert result["total"] == 1, result
    return result["items"][0]


def test_mappable_response_appears_with_coordinates(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    item = _single(client, created["response_id"])
    assert item["response_id"] == created["response_id"]
    assert item["report_id"] == report["id"]
    assert item["latitude"] == 11.2588
    assert item["longitude"] == 75.7804
    assert item["location_status"] == "CONFIRMED"
    assert item["location_confidence"] == 0.98
    assert item["response_status"] == "COMPLETED"
    assert item["need"] == "FOOD"
    assert item["activity"] == "Food parcels distributed"
    assert item["source"] == "PARTNER"


def test_response_without_location_is_excluded(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"], location=None)
    assert created["response_id"] not in _by_id(_map(client))


def test_ambiguous_location_is_excluded(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"], location="market")
    result = _map(client)
    assert created["response_id"] not in _by_id(result)


def test_null_island_projection_is_excluded(client: TestClient) -> None:
    assert is_null_island(0.0, 0.0)

    class NullIslandGeocoder:
        source: str = "null"

        def geocode(self, raw_location: str) -> list[GeocodeMatch]:
            return [
                GeocodeMatch(
                    resolved_location="Null Island",
                    latitude=0.0,
                    longitude=0.0,
                    confidence=0.5,
                )
            ]

    location_service = LocationService(NullIslandGeocoder())
    response_repository = app.dependency_overrides[get_response_repository]()
    app.dependency_overrides[get_response_map_service] = (
        lambda: ResponseMapService(response_repository, location_service)
    )
    report = _create_report(client)
    _create_response(client, report["id"], location="nowhere special")
    assert _map(client)["total"] == 0


def test_filter_by_response_status(client: TestClient) -> None:
    report = _create_report(client)
    completed = _create_response(client, report["id"])
    _create_response(
        client, report["id"], response_status="PLANNED",
        location="old bus stand",
    )
    result = _map(client, {"response_status": "COMPLETED"})
    assert set(_by_id(result)) == {completed["response_id"]}


def test_filter_by_need(client: TestClient) -> None:
    report = _create_report(client)
    food = _create_response(client, report["id"], need="FOOD")
    _create_response(
        client, report["id"], need="WATER", activity="Water delivery",
    )
    result = _map(client, {"need": "FOOD"})
    assert set(_by_id(result)) == {food["response_id"]}


def test_omits_sensitive_activity_details(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    item = _single(client, created["response_id"])
    assert SENSITIVE_KEYS.isdisjoint(item.keys())
    assert item["activity"] == "Food parcels distributed"
    assert "notes" not in item


def test_original_response_unchanged_after_mapping(client: TestClient) -> None:
    report = _create_report(client)
    created = _create_response(client, report["id"])
    _map(client)
    stored = client.get(f"/api/responses/{created['response_id']}")
    assert stored.status_code == 200
    assert stored.json()["notes"] == "operational detail"


def test_response_map_endpoint_in_openapi() -> None:
    schema = app.openapi()
    assert "/api/map/responses" in schema["paths"]
    operation = schema["paths"]["/api/map/responses"]["get"]
    names = {parameter["name"] for parameter in operation["parameters"]}
    for expected in (
        "report_id",
        "need",
        "response_status",
        "source",
        "start_time",
        "end_time",
    ):
        assert expected in names, expected
    schema_names = schema["components"]["schemas"]
    for name in ("ResponseMapItem", "ResponseMapResponse", "ResponseStatus"):
        assert name in schema_names, name