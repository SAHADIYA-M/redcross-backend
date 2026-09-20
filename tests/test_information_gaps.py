"""Phase 11 tests: Information-Gap Detection (GET /api/map/information-gaps).

The core contract under test: a lack of reports means a lack of INFORMATION,
never a lack of NEED. The information-gap score is a separate concept from
the Phase 8 priority score and is never fused with it.

Cells (grid, cell_size=0.01):
    A = cell:11.25:75.78   (kozhikode beach, mananchira, railway station)
    B = cell:11.26:75.76   (old bus stand, medical college)
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.map import get_information_gap_service
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.api.verification import get_audit_repository, get_verification_service
from app.information_gap.schemas import InformationGapStatus
from app.location.providers import StubGeocoder
from app.location.service import LocationService
from app.main import app
from app.repositories import InMemoryReportRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.services.information_gap_service import (
    InformationGapService,
    recency_factor_score,
)
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.verification.service import VerificationService

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

CELL_SIZE = 0.01
CELL_A = "cell:11.25:75.78"
CELL_B = "cell:11.26:75.76"

EMPTY_AREA_REASON = "No reports available for this area."


def _ts(days_ago: int = 0, hours_ago: int = 0) -> str:
    return (NOW - timedelta(days=days_ago, hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@pytest.fixture()
def client(auth_setup, admin_headers):
    """Clean, isolated in-memory storage with a fixed reference clock. The
    client is pre-authenticated as the seeded ADMIN user."""
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
    app.dependency_overrides[get_information_gap_service] = (
        lambda: InformationGapService(
            report_repository,
            location_service,
            now=NOW,
        )
    )
    with TestClient(app) as test_client:
        test_client.headers.update(admin_headers)
        yield test_client
    app.dependency_overrides.clear()


def _create(client: TestClient, location: str, **overrides) -> dict:
    payload = {
        "original_text": "Families need drinking water after the flood",
        "reporter": "field_team_01",
        "location": location,
        "incident": "Flood",
        "timestamp": _ts(),
        "source": "S1",
        "location_status": "CONFIRMED",
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client: TestClient, report_id: str) -> None:
    response = client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "APPROVE", "reason": "confirmed by coordinator"},
    )
    assert response.status_code == 200, response.text


def _gaps(client: TestClient, params=None) -> dict:
    response = client.get("/api/map/information-gaps", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _areas_by_id(result: dict) -> dict[str, dict]:
    return {area["area_id"]: area for area in result["areas"]}


def _area(client: TestClient, area_id: str, params=None) -> dict:
    result = _gaps(client, params)
    areas = _areas_by_id(result)
    assert area_id in areas, areas
    return areas[area_id]


# ------------------------------------------------------------- well-covered


def test_well_covered_recent_verified_area_is_sufficient(client: TestClient) -> None:
    for index in range(10):
        _create(
            client,
            "kozhikode beach",
            source=f"S{index % 4}",
            timestamp=_ts(hours_ago=1),
        )
    created = client.get("/api/reports").json()
    for report in created[:8]:
        _approve(client, report["id"])

    area = _area(client, CELL_A, {"cell_size": CELL_SIZE})
    assert area["report_count"] == 10
    assert area["distinct_sources"] == 4
    assert area["latest_report_at"] == _ts(hours_ago=1)
    assert area["information_gap_score"] == 3
    assert area["information_status"] == InformationGapStatus.SUFFICIENT_INFORMATION.value
    assert "No reports available for this area." not in area["reasons"]


# ------------------------------------------------------------- zero reports


def test_area_with_no_reports_is_insufficient_information(client: TestClient) -> None:
    params = {
        "cell_size": CELL_SIZE,
        "min_lat": 10.0,
        "max_lat": 10.02,
        "min_lon": 74.0,
        "max_lon": 74.02,
    }
    result = _gaps(client, params)
    assert result["total"] == 4  # 2x2 grid, all empty
    for area in result["areas"]:
        assert area["report_count"] == 0
        assert area["latest_report_at"] is None
        assert area["distinct_sources"] == 0
        assert area["information_gap_score"] == 100
        assert area["information_status"] == InformationGapStatus.INSUFFICIENT_INFORMATION.value
        assert EMPTY_AREA_REASON in area["reasons"]


def test_zero_report_cell_is_enumerated_alongside_populated_cells(
    client: TestClient,
) -> None:
    _create(client, "kozhikode beach", timestamp=_ts())
    params = {
        "cell_size": CELL_SIZE,
        "min_lat": 11.25,
        "max_lat": 11.27,
        "min_lon": 75.76,
        "max_lon": 75.79,
    }
    result = _gaps(client, params)
    areas = _areas_by_id(result)
    assert result["total"] == 6  # 2 lat x 3 lon cells
    assert areas[CELL_A]["report_count"] == 1
    assert areas[CELL_A]["information_status"] == InformationGapStatus.LIMITED_INFORMATION.value
    assert areas[CELL_B]["report_count"] == 0
    assert areas[CELL_B]["information_status"] == InformationGapStatus.INSUFFICIENT_INFORMATION.value
    assert EMPTY_AREA_REASON in areas[CELL_B]["reasons"]


def test_no_reports_and_no_bbox_returns_empty(client: TestClient) -> None:
    result = _gaps(client, {"cell_size": CELL_SIZE})
    assert result["areas"] == []
    assert result["total"] == 0


# --------------------------------------------------------------- staleness


def test_old_reports_increase_information_gap(client: TestClient) -> None:
    for _ in range(3):
        _create(client, "kozhikode beach", timestamp=_ts(days_ago=40))
    for _ in range(3):
        _create(client, "old bus stand", timestamp=_ts(hours_ago=1))

    result = _gaps(client, {"cell_size": CELL_SIZE})
    areas = _areas_by_id(result)
    old = areas[CELL_A]
    fresh = areas[CELL_B]
    assert old["information_gap_score"] > fresh["information_gap_score"]
    assert old["information_status"] == InformationGapStatus.LIMITED_INFORMATION.value
    assert fresh["information_status"] == InformationGapStatus.SUFFICIENT_INFORMATION.value
    assert "No recent reports" in old["reasons"]
    assert "No recent reports" not in fresh["reasons"]


# ----------------------------------------------------------- verification


def test_unverified_reports_increase_information_gap(client: TestClient) -> None:
    verified_ids = []
    for _ in range(3):
        verified_ids.append(_create(client, "kozhikode beach", timestamp=_ts())["id"])
    for _ in range(3):
        _create(client, "old bus stand", timestamp=_ts())
    for report_id in verified_ids:
        _approve(client, report_id)

    areas = _areas_by_id(_gaps(client, {"cell_size": CELL_SIZE}))
    verified = areas[CELL_A]
    unverified = areas[CELL_B]
    assert unverified["information_gap_score"] > verified["information_gap_score"]
    assert "No verified reports" in unverified["reasons"]
    assert "No verified reports" not in verified["reasons"]


def test_rejected_reports_are_not_verified_evidence(client: TestClient) -> None:
    rejected_ids = []
    for _ in range(3):
        rejected_ids.append(_create(client, "kozhikode beach", timestamp=_ts())["id"])
    for report_id in rejected_ids:
        response = client.patch(
            f"/api/reports/{report_id}/verify",
            json={"action": "REJECT", "reason": "false information"},
        )
        assert response.status_code == 200, response.text

    area = _area(client, CELL_A, {"cell_size": CELL_SIZE})
    assert area["report_count"] == 3
    assert "No verified reports" in area["reasons"]


# ------------------------------------------------- location uncertainty


def test_uncertain_locations_increase_information_uncertainty(
    client: TestClient,
) -> None:
    for _ in range(3):
        _create(client, "kozhikode beach", location_status="CONFIRMED")
    for _ in range(3):
        _create(client, "old bus stand", location_status="UNCERTAIN")

    areas = _areas_by_id(_gaps(client, {"cell_size": CELL_SIZE}))
    confirmed = areas[CELL_A]
    uncertain = areas[CELL_B]
    assert uncertain["information_gap_score"] > confirmed["information_gap_score"]
    assert uncertain["information_status"] == InformationGapStatus.LIMITED_INFORMATION.value
    assert "Many reports have uncertain locations" in uncertain["reasons"]
    assert "uncertain locations" not in "".join(confirmed["reasons"])


# ------------------------------------------------------- source diversity


def test_multiple_sources_lower_gap_than_single_source(client: TestClient) -> None:
    sources = ["S1", "S2", "S3"]
    for index, source in enumerate(sources):
        _create(client, "kozhikode beach", source=source, timestamp=_ts())
    for _ in range(3):
        _create(client, "old bus stand", source="S1", timestamp=_ts())

    areas = _areas_by_id(_gaps(client, {"cell_size": CELL_SIZE}))
    multi = areas[CELL_A]
    single = areas[CELL_B]
    assert multi["distinct_sources"] == 3
    assert single["distinct_sources"] == 1
    assert single["information_gap_score"] > multi["information_gap_score"]
    assert "Reports come from only one source" in single["reasons"]
    assert "Reports come from only one source" not in multi["reasons"]


def test_missing_source_information_increases_gap(client: TestClient) -> None:
    for _ in range(3):
        _create(client, "kozhikode beach", source=None)

    area = _area(client, CELL_A, {"cell_size": CELL_SIZE})
    assert area["distinct_sources"] == 0
    assert area["information_gap_score"] == 45
    assert area["information_status"] == InformationGapStatus.LIMITED_INFORMATION.value
    assert "No source information available" in area["reasons"]


# ------------------------------------------------------------ missing data


def test_missing_timestamps_are_not_treated_as_recent() -> None:
    assert recency_factor_score(None, NOW) == 100.0
    assert recency_factor_score(NOW, NOW) == 0.0


# ---------------------------------------------- no "no need" false positives


def test_zero_reports_never_concludes_low_need(client: TestClient) -> None:
    params = {
        "cell_size": CELL_SIZE,
        "min_lat": 10.0,
        "max_lat": 10.01,
        "min_lon": 74.0,
        "max_lon": 74.01,
    }
    result = _gaps(client, params)
    area = result["areas"][0]
    assert area["information_status"] == InformationGapStatus.INSUFFICIENT_INFORMATION.value
    assert EMPTY_AREA_REASON in area["reasons"]
    for forbidden in ("need_level", "priority", "priority_level", "priority_score", "needs"):
        assert forbidden not in area, forbidden


def test_gap_score_is_separate_from_priority_score(client: TestClient) -> None:
    report = _create(
        client,
        "kozhikode beach",
        severity="CRITICAL",
        affected_population=5000,
        vulnerability=["children", "elderly"],
        time_sensitivity="within 24 hours",
        evidence=["crowded"],
        timestamp=_ts(),
    )
    priority = client.post(f"/api/reports/{report['id']}/priority")
    assert priority.status_code == 200, priority.text
    assert priority.json()["priority_level"] == "CRITICAL"

    area = _area(client, CELL_A, {"cell_size": CELL_SIZE})
    # The same report is operationally urgent but informationally thin.
    assert area["information_status"] == InformationGapStatus.LIMITED_INFORMATION.value
    assert area["information_gap_score"] > 0
    assert "priority_level" not in area
    assert "priority_score" not in area


# -------------------------------------------------------------- reasons


def test_reasons_accurately_reflect_signals(client: TestClient) -> None:
    for _ in range(2):
        _create(client, "kozhikode beach", source="S1", timestamp=_ts(days_ago=10))
    area = _area(client, CELL_A, {"cell_size": CELL_SIZE})
    # Two reports, 10 days old, one source, none verified, all confirmed.
    assert "No recent reports" in area["reasons"]
    assert "Few reports" in area["reasons"]
    assert "Reports come from only one source" in area["reasons"]
    assert "No verified reports" in area["reasons"]
    assert not any("uncertain locations" in r for r in area["reasons"])


def test_reasons_empty_when_everything_is_well_covered(client: TestClient) -> None:
    for index in range(10):
        _create(
            client,
            "kozhikode beach",
            source=f"S{index % 4}",
            timestamp=_ts(hours_ago=1),
        )
    for report in client.get("/api/reports").json():
        _approve(client, report["id"])
    area = _area(client, CELL_A, {"cell_size": CELL_SIZE})
    assert area["reasons"] == []


# ------------------------------------------------------------ validation


def test_partial_bounding_box_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/map/information-gaps",
        params={"min_lat": 10.0, "max_lat": 10.1},
    )
    assert response.status_code == 422


def test_inverted_bounding_box_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/map/information-gaps",
        params={"min_lat": 11.2, "max_lat": 11.1, "min_lon": 75.6, "max_lon": 75.7},
    )
    assert response.status_code == 422


def test_cell_size_out_of_range_rejected(client: TestClient) -> None:
    assert client.get("/api/map/information-gaps", params={"cell_size": 0.0}).status_code == 422
    assert client.get("/api/map/information-gaps", params={"cell_size": 2.0}).status_code == 422


# ---------------------------------------------------------------- OpenAPI


def test_information_gaps_endpoint_in_openapi() -> None:
    schema = app.openapi()
    assert "/api/map/information-gaps" in schema["paths"]
    parameters = schema["paths"]["/api/map/information-gaps"]["get"]["parameters"]
    names = {parameter["name"] for parameter in parameters}
    for expected in ("min_lat", "max_lat", "min_lon", "max_lon", "cell_size"):
        assert expected in names, expected
    for schema_name in (
        "InformationGapArea",
        "InformationGapResponse",
        "InformationGapStatus",
    ):
        assert schema_name in schema["components"]["schemas"]
    status_schema = schema["components"]["schemas"]["InformationGapStatus"]
    for value in (
        "SUFFICIENT_INFORMATION",
        "LIMITED_INFORMATION",
        "INSUFFICIENT_INFORMATION",
    ):
        assert value in status_schema["enum"]