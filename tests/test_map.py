"""Phase 11 tests: Map API (GET /api/map/reports).

Covers coordinate validation (only valid, non-0,0 coordinates map), location
uncertainty preservation (CONFIRMED/UNCERTAIN/confidence), every supported
filter (need, priority, verification, status, incident, source, time,
bounding box), privacy-safe output and "original data is never mutated".
"""

import pytest
from fastapi.testclient import TestClient

from app.api.map import get_information_gap_service, get_map_service
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.api.verification import get_audit_repository, get_verification_service
from app.location.providers import StubGeocoder
from app.location.schemas import GeocodeMatch
from app.location.service import LocationService
from app.main import app
from app.repositories import InMemoryReportRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.search.service import SearchService
from app.services.information_gap_service import InformationGapService
from app.services.map_service import MapService, is_null_island
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.verification.service import VerificationService

BASE_TIME = "2026-09-20T10:00:00Z"

# Coordinator must not be leaked to the map.
SENSITIVE_KEYS = {"original_text", "reporter", "evidence", "vulnerability"}


@pytest.fixture()
def client():
    """Clean, isolated in-memory storage with the Phase 11 services wired to
    the SAME repository as the reports API and the stub geocoder."""
    report_repository = InMemoryReportRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()
    location_service = LocationService(StubGeocoder())

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
    app.dependency_overrides[get_priority_service] = (
        lambda: PriorityService(report_repository)
    )
    app.dependency_overrides[get_map_service] = (
        lambda: MapService(
            SearchService(report_repository, PriorityService(report_repository), location_service),
            location_service,
        )
    )
    app.dependency_overrides[get_information_gap_service] = (
        lambda: InformationGapService(report_repository, location_service)
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _map_over(client: TestClient, geocoder: object) -> None:
    """Point the map endpoint at a scriptable geocoder (same repository)."""
    repository = app.dependency_overrides[get_report_service]()._repository  # type: ignore[attr-defined]
    location_service = LocationService(geocoder)  # type: ignore[arg-type]
    service = MapService(
        SearchService(repository, PriorityService(repository), location_service),
        location_service,
    )
    app.dependency_overrides[get_map_service] = lambda: service


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "No drinking water for the children at the beach",
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "incident": "Flood",
        "timestamp": BASE_TIME,
        "source": "FIELD_REPORT",
        "location_status": "CONFIRMED",
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _map(client: TestClient, params=None) -> dict:
    response = client.get("/api/map/reports", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _by_id(result: dict) -> dict[str, dict]:
    return {item["report_id"]: item for item in result["items"]}


def _single_item(client: TestClient, report_id: str) -> dict:
    result = _map(client)
    assert result["total"] == 1, result
    return result["items"][0]


# ----------------------------------------------------------- valid coordinates


def test_report_with_valid_coordinates_appears_on_map(client: TestClient) -> None:
    report = _create(client, location_status="CONFIRMED")
    item = _single_item(client, report["id"])
    assert item["report_id"] == report["id"]
    assert item["latitude"] == 11.2588
    assert item["longitude"] == 75.7804


def test_report_without_location_is_excluded(client: TestClient) -> None:
    report = _create(client, location=None)
    assert _map(client)["total"] == 0
    assert report["id"] not in _by_id(_map(client))


def test_report_without_geocodable_location_is_excluded(client: TestClient) -> None:
    _create(client, location="a place unknown to any geocoder")
    assert _map(client)["total"] == 0


def test_report_with_ambiguous_location_is_excluded(client: TestClient) -> None:
    # "market" and "hospital" resolve to multiple candidates -> never mapped.
    market = _create(client, location="market", location_status="UNCERTAIN")
    result = _map(client)
    assert market["id"] not in _by_id(result)


def test_invalid_bounding_box_coordinates_rejected(client: TestClient) -> None:
    assert client.get("/api/map/reports", params={"min_lat": 95}).status_code == 422
    assert client.get("/api/map/reports", params={"max_lon": 200}).status_code == 422
    assert (
        client.get(
            "/api/map/reports",
            params={"min_lat": 11.3, "max_lat": 11.2, "min_lon": 75.7, "max_lon": 75.8},
        ).status_code
        == 422
    )


# --------------------------------------------------------------- 0,0 fallback


def test_null_island_is_detected() -> None:
    assert is_null_island(0.0, 0.0)
    assert not is_null_island(11.2588, 75.7804)
    assert not is_null_island(0.0, 75.7)
    assert not is_null_island(11.2, 0.0)


def test_null_island_geocode_is_not_used_as_fallback(client: TestClient) -> None:
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

    _map_over(client, NullIslandGeocoder())
    report = _create(client, location="nowhere special")
    assert _map(client)["total"] == 0


# ------------------------------------------------------- location uncertainty


def test_confirmed_location_stays_confirmed(client: TestClient) -> None:
    report = _create(client, location_status="CONFIRMED")
    item = _single_item(client, report["id"])
    assert item["location_status"] == "CONFIRMED"


def test_uncertain_location_stays_uncertain(client: TestClient) -> None:
    # A geocodable location that Phase 5 marked UNCERTAIN must keep that
    # status on the map; it is never silently upgraded to CONFIRMED.
    report = _create(client, location_status="UNCERTAIN")
    item = _single_item(client, report["id"])
    assert item["location_status"] == "UNCERTAIN"


def test_map_marker_still_has_coordinates_for_uncertain_report(
    client: TestClient,
) -> None:
    report = _create(client, location_status="UNCERTAIN")
    item = _single_item(client, report["id"])
    assert item["latitude"] == 11.2588
    assert item["longitude"] == 75.7804


def test_location_confidence_is_preserved(client: TestClient) -> None:
    report = _create(client, location="kozhikode beach")
    item = _single_item(client, report["id"])
    assert item["location_confidence"] == 0.98


def test_location_confidence_is_null_when_unavailable(client: TestClient) -> None:
    class NoConfidenceGeocoder:
        source: str = "no-conf"

        def geocode(self, raw_location: str) -> list[GeocodeMatch]:
            return [
                GeocodeMatch(
                    resolved_location="Old Bus Stand, Kozhikode, Kerala, India",
                    latitude=11.2602,
                    longitude=75.7620,
                )
            ]

    _map_over(client, NoConfidenceGeocoder())
    report = _create(client, location="old bus stand")
    item = _single_item(client, report["id"])
    assert item["location_confidence"] is None


# ------------------------------------------------------------------- filters


def test_need_filter_works(client: TestClient) -> None:
    water = _create(client, needs=["WATER"], location_status="CONFIRMED")
    food = _create(
        client,
        location="old bus stand",
        needs=["FOOD", "SHELTER"],
        location_status="CONFIRMED",
    )
    result = _map(client, {"need": "WATER"})
    by_id = _by_id(result)
    assert water["id"] in by_id
    assert food["id"] not in by_id
    result = _map(client, [("need", "FOOD"), ("need", "SHELTER")])
    assert food["id"] in _by_id(result)


def test_priority_filter_works(client: TestClient) -> None:
    high = _create(
        client,
        severity="CRITICAL",
        affected_population=5000,
        vulnerability=["children"],
        time_sensitivity="within 24 hours",
        evidence=["crowded"],
        location_status="CONFIRMED",
    )
    low = _create(client, severity="LOW", affected_population=5, location_status="CONFIRMED")
    result = _map(client, {"priority": "HIGH"})
    by_id = _by_id(result)
    assert high["id"] in by_id
    assert low["id"] not in by_id


def test_verification_filter_works(client: TestClient) -> None:
    verified = _create(client, location_status="CONFIRMED")
    unverified = _create(
        client, location="old bus stand", location_status="CONFIRMED"
    )
    client.patch(
        f"/api/reports/{verified['id']}/verify",
        json={"action": "APPROVE", "reason": "confirmed by coordinator"},
    )
    result = _map(client, {"verification_status": "VERIFIED"})
    by_id = _by_id(result)
    assert verified["id"] in by_id
    assert unverified["id"] not in by_id


def test_report_status_filter_works(client: TestClient) -> None:
    a = _create(client, location_status="CONFIRMED")
    b = _create(client, location="old bus stand", location_status="CONFIRMED")
    client.patch(f"/api/reports/{b['id']}", json={"status": "IN_REVIEW"})
    result = _map(client, {"report_status": "IN_REVIEW"})
    by_id = _by_id(result)
    assert b["id"] in by_id
    assert a["id"] not in by_id


def test_incident_filter_works(client: TestClient) -> None:
    a = _create(client, incident="Flood", location_status="CONFIRMED")
    b = _create(client, incident="Cyclone", location="old bus stand", location_status="CONFIRMED")
    result = _map(client, {"incident": "flood"})
    by_id = _by_id(result)
    assert a["id"] in by_id
    assert b["id"] not in by_id


def test_source_filter_works(client: TestClient) -> None:
    a = _create(client, source="PARTNER", location_status="CONFIRMED")
    b = _create(client, source="OFFICIAL", location="old bus stand", location_status="CONFIRMED")
    result = _map(client, {"source": "partner"})
    by_id = _by_id(result)
    assert a["id"] in by_id
    assert b["id"] not in by_id


def test_time_filter_works(client: TestClient) -> None:
    older = _create(
        client, timestamp="2026-09-19T10:00:00Z", location_status="CONFIRMED"
    )
    newer = _create(
        client,
        location="old bus stand",
        timestamp="2026-09-20T10:00:00Z",
        location_status="CONFIRMED",
    )
    result = _map(
        client,
        {"start_time": "2026-09-20T00:00:00Z", "end_time": "2026-09-20T23:59:59Z"},
    )
    by_id = _by_id(result)
    assert newer["id"] in by_id
    assert older["id"] not in by_id


def test_geographic_bounding_box_filter_works(client: TestClient) -> None:
    inside = _create(client, location="kozhikode beach", location_status="CONFIRMED")
    outside = _create(client, location="old bus stand", location_status="CONFIRMED")
    # Box around kozhikode beach only.
    result = _map(
        client,
        {"min_lat": 11.25, "max_lat": 11.27, "min_lon": 75.77, "max_lon": 75.79},
    )
    by_id = _by_id(result)
    assert inside["id"] in by_id
    assert outside["id"] not in by_id


def test_bbox_never_includes_unmappable_reports(client: TestClient) -> None:
    # A box covering the whole gazetteer still excludes the ambiguous report.
    ambiguous = _create(client, location="market", location_status="UNCERTAIN")
    result = _map(
        client,
        {"min_lat": 11.2, "max_lat": 11.3, "min_lon": 75.6, "max_lon": 75.9},
    )
    assert ambiguous["id"] not in _by_id(result)


def test_invalid_filter_enums_rejected(client: TestClient) -> None:
    assert client.get("/api/map/reports", params={"need": "BOGUS"}).status_code == 422
    assert client.get("/api/map/reports", params={"priority": "TURBO"}).status_code == 422
    assert (
        client.get(
            "/api/map/reports", params={"verification_status": "MAYBE"}
        ).status_code
        == 422
    )
    assert (
        client.get("/api/map/reports", params={"report_status": "MAYBE"}).status_code
        == 422
    )


def test_inverted_time_range_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/map/reports",
        params={"start_time": "2026-01-02T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"},
    )
    assert response.status_code == 422


# ------------------------------------------------- hygiene: privacy & integrity


def test_map_item_omits_sensitive_fields(client: TestClient) -> None:
    _create(client, location_status="CONFIRMED", evidence=["crowded", "flooded"])
    item = _single_item(client, "any")
    assert SENSITIVE_KEYS.isdisjoint(item.keys())


def test_map_item_contains_dashboard_fields(client: TestClient) -> None:
    report = _create(
        client,
        needs=["WATER"],
        severity="HIGH",
        affected_population=300,
        location_status="CONFIRMED",
    )
    item = _single_item(client, report["id"])
    assert item["report_id"] == report["id"]
    assert item["needs"] == ["WATER"]
    assert item["priority_level"] == "MEDIUM"
    assert item["priority_score"] == 53.5
    assert item["verification_status"] == "UNVERIFIED"
    assert item["report_status"] == "RECEIVED"
    assert item["source"] == "FIELD_REPORT"
    assert item["incident"] == "Flood"
    assert item["timestamp"] == BASE_TIME


def test_original_report_data_remains_unchanged(client: TestClient) -> None:
    report = _create(client, location_status="CONFIRMED")
    _map(client)
    _map(client, {"need": "WATER"})
    _map(client, {"min_lat": 11.2, "max_lat": 11.3, "min_lon": 75.6, "max_lon": 75.9})
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["original_text"] == report["original_text"]
    assert stored["location"] == report["location"]
    assert stored["source"] == report["source"]
    assert stored["timestamp"] == report["timestamp"]


def test_empty_map_is_not_an_opinion_about_need(client: TestClient) -> None:
    _create(client, location=None)
    result = _map(client)
    assert result["items"] == []
    assert result["total"] == 0


# ---------------------------------------------------------------- OpenAPI


def test_map_endpoint_in_openapi() -> None:
    schema = app.openapi()
    assert "/api/map/reports" in schema["paths"]
    parameters = schema["paths"]["/api/map/reports"]["get"]["parameters"]
    names = {parameter["name"] for parameter in parameters}
    for expected in (
        "need",
        "priority",
        "min_priority_score",
        "verification_status",
        "report_status",
        "incident",
        "source",
        "start_time",
        "end_time",
        "min_lat",
        "max_lat",
        "min_lon",
        "max_lon",
    ):
        assert expected in names, expected
    for schema_name in ("MapResponse", "MapReportItem", "MapSortField", "MapSortOrder"):
        assert schema_name in schema["components"]["schemas"]
    assert "InformationGapStatus" in schema["components"]["schemas"]