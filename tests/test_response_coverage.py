"""Phase 12 tests: Response Coverage (GET /api/analytics/response-coverage).

The core contract under test:
- RESPONSE_RECORDED / NO_RESPONSE_RECORDED / PARTIAL_RESPONSE_RECORDED are
  statements about what is RECORDED in this system, never about the real world;
- "no response recorded" never becomes "no response exists" or "unmet need";
- priority (Phase 8) and verification (Phase 9) are preserved but separate;
- the information gap (Phase 11) stays distinct from the response gap;
- quantitative coverage is only computed when both sides of the ratio exist.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.analytics import get_response_coverage_service
from app.api.map import get_information_gap_service
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.api.responses import get_response_repository, get_response_service
from app.api.verification import get_audit_repository, get_verification_service
from app.location.providers import StubGeocoder
from app.location.service import LocationService
from app.main import app
from app.repositories import InMemoryReportRepository, InMemoryResponseRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.services.information_gap_service import InformationGapService
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.services.response_coverage_service import ResponseCoverageService
from app.services.response_service import ResponseService
from app.verification.service import VerificationService

REPORT_TIME = "2026-09-20T08:00:00Z"
RESPONSE_TIME = "2026-09-20T10:00:00Z"


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
    app.dependency_overrides[get_response_coverage_service] = (
        lambda: ResponseCoverageService(
            report_repository,
            response_repository,
            PriorityService(report_repository),
        )
    )
    app.dependency_overrides[get_information_gap_service] = (
        lambda: InformationGapService(report_repository, location_service)
    )
    with TestClient(app) as test_client:
        test_client.headers.update(admin_headers)
        yield test_client
    app.dependency_overrides.clear()


def _create_report(client: TestClient, needs=("WATER",), **overrides) -> dict:
    payload = {
        "original_text": "Families need drinking water after the flood",
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "incident": "Flood",
        "timestamp": REPORT_TIME,
        "source": "FIELD_REPORT",
        "needs": list(needs),
        "affected_population": 100,
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_response(
    client: TestClient, report_id: str, need="WATER", **overrides
) -> dict:
    payload = {
        "report_id": report_id,
        "need": need,
        "activity": "Water tanker dispatched",
        "response_status": "COMPLETED",
        "timestamp": RESPONSE_TIME,
        "source": "PARTNER",
        "affected_population": None,
    }
    payload.update(overrides)
    response = client.post("/api/responses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _coverage(client: TestClient, params=None) -> dict:
    response = client.get("/api/analytics/response-coverage", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _row(client: TestClient, report_id: str, need="WATER", params=None) -> dict:
    result = _coverage(client, params)
    matches = [
        item for item in result["items"]
        if item["report_id"] == report_id and item["need"] == need
    ]
    assert len(matches) == 1, result
    return matches[0]


def _approve(client: TestClient, report_id: str) -> None:
    response = client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "APPROVE", "reason": "confirmed by coordinator"},
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------------- coverage basics


def test_completed_response_records_coverage(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"])
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["response_count"] == 1
    assert row["active_response_statuses"] == ["COMPLETED"]
    assert row["latest_response_at"] == RESPONSE_TIME


def test_in_progress_response_records_coverage(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"], response_status="IN_PROGRESS")
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["active_response_statuses"] == ["IN_PROGRESS"]


def test_planned_response_documented_behavior(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"], response_status="PLANNED")
    row = _row(client, report["id"])
    # A PLANNED activity is genuinely recorded, so it is RESPONSE_RECORDED;
    # its distinct status keeps "not yet underway" explicit.
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["response_count"] == 1
    assert row["active_response_statuses"] == ["PLANNED"]


def test_cancelled_only_response_is_not_active_coverage(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"], response_status="CANCELLED")
    row = _row(client, report["id"])
    assert row["response_status"] == "NO_RESPONSE_RECORDED"
    assert row["response_count"] == 0
    assert row["active_response_statuses"] == []
    assert row["coverage_percentage"] is None


def test_cancelled_alongside_active_does_not_inflate_count(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"])
    _create_response(client, report["id"], response_status="CANCELLED",
                     activity="Scrapped delivery", affected_population=40)
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["response_count"] == 1
    assert row["active_response_statuses"] == ["COMPLETED"]


def test_no_response_is_no_response_recorded(client: TestClient) -> None:
    report = _create_report(client)
    row = _row(client, report["id"])
    assert row["response_status"] == "NO_RESPONSE_RECORDED"
    assert row["response_count"] == 0
    assert row["latest_response_at"] is None
    assert row["coverage_percentage"] is None


def test_multiple_responses_counted(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"], activity="Water tanker 1")
    _create_response(client, report["id"], activity="Water tanker 2",
                     timestamp="2026-09-20T12:00:00Z")
    row = _row(client, report["id"])
    assert row["response_count"] == 2
    assert set(row["active_response_statuses"]) == {"COMPLETED"}
    assert row["latest_response_at"] == "2026-09-20T12:00:00Z"


def test_needless_response_never_counts_toward_specific_need(
    client: TestClient,
) -> None:
    report = _create_report(client)
    _create_response(client, report["id"], need=None,
                     activity="Assessment team deployed")
    row = _row(client, report["id"])
    # The system does not guess which need a general response served.
    assert row["response_status"] == "NO_RESPONSE_RECORDED"
    assert row["response_count"] == 0


def test_rows_are_emitted_per_reported_need(client: TestClient) -> None:
    report = _create_report(client, needs=("WATER", "FOOD"))
    _create_response(client, report["id"], need="WATER")
    result = _coverage(client)
    rows = {
        item["need"]: item for item in result["items"]
        if item["report_id"] == report["id"]
    }
    assert rows["WATER"]["response_status"] == "RESPONSE_RECORDED"
    assert rows["FOOD"]["response_status"] == "NO_RESPONSE_RECORDED"
    assert rows["FOOD"]["response_count"] == 0


def test_second_need_is_not_covered_by_water_response(client: TestClient) -> None:
    report = _create_report(client, needs=("WATER", "SHELTER"))
    _create_response(client, report["id"], need="WATER")
    shelter = _row(client, report["id"], need="SHELTER")
    assert shelter["response_status"] == "NO_RESPONSE_RECORDED"
    assert shelter["response_count"] == 0


# --------------------------------------------- priority / verification keep


def test_priority_level_and_score_preserved(client: TestClient) -> None:
    report = _create_report(
        client,
        severity="CRITICAL",
        affected_population=5000,
        vulnerability=["children", "elderly"],
        time_sensitivity="within 24 hours",
        evidence=["crowded"],
    )
    # No response recorded -> still identifiable as CRITICAL.
    row = _row(client, report["id"])
    assert row["priority_level"] == "CRITICAL"
    assert row["priority_score"] == 87.75
    assert row["response_status"] == "NO_RESPONSE_RECORDED"


def test_critical_no_response_vs_low_no_response_and_priority_filter(
    client: TestClient,
) -> None:
    critical = _create_report(
        client,
        severity="CRITICAL",
        affected_population=5000,
        vulnerability=["children", "elderly"],
        time_sensitivity="within 24 hours",
        evidence=["crowded"],
    )
    low = _create_report(
        client,
        location="old bus stand",
        severity="LOW",
        affected_population=5,
    )
    result = _coverage(client)
    by_id = {item["report_id"]: item for item in result["items"]}
    assert by_id[critical["id"]]["priority_level"] == "CRITICAL"
    assert by_id[low["id"]]["priority_level"] == "LOW"
    assert by_id[critical["id"]]["response_status"] == "NO_RESPONSE_RECORDED"
    assert by_id[low["id"]]["response_status"] == "NO_RESPONSE_RECORDED"

    filtered = _coverage(client, {"priority": "CRITICAL"})
    filtered_ids = {item["report_id"] for item in filtered["items"]}
    assert critical["id"] in filtered_ids
    assert low["id"] not in filtered_ids


def test_verification_status_is_preserved(client: TestClient) -> None:
    verified = _create_report(client)
    unverified = _create_report(client, location="old bus stand")
    _approve(client, verified["id"])
    _create_response(client, verified["id"])

    result = _coverage(client)
    by_id = {item["report_id"]: item for item in result["items"]}
    assert by_id[verified["id"]]["verification_status"] == "VERIFIED"
    assert by_id[unverified["id"]]["verification_status"] == "UNVERIFIED"

    filtered = _coverage(client, {"verification_status": "VERIFIED"})
    assert {item["report_id"] for item in filtered["items"]} == {verified["id"]}


def test_unverified_need_with_response_stays_unverified(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"])
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["verification_status"] == "UNVERIFIED"


def test_uncertain_location_stays_uncertain(client: TestClient) -> None:
    report = _create_report(client, location_status="UNCERTAIN")
    _create_response(client, report["id"])
    row = _row(client, report["id"])
    assert row["location"] == "kozhikode beach"
    assert row["location_status"] == "UNCERTAIN"


# ----------------------------------------------------- quantitative coverage


def test_partial_quantitative_coverage(client: TestClient) -> None:
    report = _create_report(client, affected_population=100)
    _create_response(client, report["id"], affected_population=40)
    row = _row(client, report["id"])
    assert row["response_status"] == "PARTIAL_RESPONSE_RECORDED"
    assert row["coverage_percentage"] == 40.0


def test_full_quantitative_coverage(client: TestClient) -> None:
    report = _create_report(client, affected_population=100)
    _create_response(client, report["id"], affected_population=100)
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["coverage_percentage"] == 100.0


def test_multiple_responses_sum_reached_population(client: TestClient) -> None:
    report = _create_report(client, affected_population=100)
    _create_response(client, report["id"], affected_population=30)
    _create_response(
        client, report["id"], affected_population=20,
        activity="Second delivery",
    )
    row = _row(client, report["id"])
    assert row["response_status"] == "PARTIAL_RESPONSE_RECORDED"
    assert row["coverage_percentage"] == 50.0


def test_numeric_coverage_not_computed_without_reported_population(
    client: TestClient,
) -> None:
    report = _create_report(client, affected_population=None)
    _create_response(client, report["id"], affected_population=40)
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["coverage_percentage"] is None


def test_numeric_coverage_not_computed_without_reached_population(
    client: TestClient,
) -> None:
    report = _create_report(client, affected_population=100)
    _create_response(client, report["id"], affected_population=None)
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert row["coverage_percentage"] is None


def test_none_never_treated_as_zero_percent_covered(client: TestClient) -> None:
    report = _create_report(client, affected_population=None)
    _create_response(client, report["id"])
    row = _row(client, report["id"])
    assert row["coverage_percentage"] is None


# ---------------------------------------------------------------- filters


def test_need_filter_limits_rows_to_that_need(client: TestClient) -> None:
    report = _create_report(client, needs=("WATER", "FOOD"))
    _create_response(client, report["id"], need="WATER")
    result = _coverage(client, {"need": "WATER"})
    assert {item["need"] for item in result["items"]} == {"WATER"}


def test_report_id_filter(client: TestClient) -> None:
    report_a = _create_report(client)
    report_b = _create_report(client, location="old bus stand")
    result = _coverage(client, {"report_id": report_b["id"]})
    assert {item["report_id"] for item in result["items"]} == {report_b["id"]}
    assert report_a["id"] not in {i["report_id"] for i in result["items"]}


# ---------------------------------------- safety: no response exists claims


def test_no_response_does_not_claim_no_response_exists(client: TestClient) -> None:
    report = _create_report(client)
    _create_response(client, report["id"])
    row = _row(client, report["id"])
    assert row["response_status"] == "RESPONSE_RECORDED"


def test_coverage_status_enum_has_no_existing_claim(client: TestClient) -> None:
    schema = app.openapi()
    enum = schema["components"]["schemas"]["CoverageStatus"]["enum"]
    assert "NO_RESPONSE_RECORDED" in enum
    for forbidden in ("NO_RESPONSE_EXISTS", "NO_ONE_RESPONDING", "UNMET_NEED"):
        assert forbidden not in enum, forbidden
        assert forbidden not in " ".join(enum), forbidden


def test_empty_coverage_never_implies_no_need(client: TestClient) -> None:
    # No reports at all -> zero coverage rows and NO "no need" conclusion.
    result = _coverage(client)
    assert result["items"] == []
    assert result["total"] == 0
    # A report with no classified needs also produces no rows: an absent row
    # is not a verdict. Nothing in the model claims "need resolved".
    _create_report(client, needs=())
    result = _coverage(client)
    assert result["total"] == 0
    item_keys = set()
    for item in result["items"]:
        item_keys |= set(item)
    assert "need_level" not in item_keys
    assert "no_need" not in item_keys


# ------------------------------------------- information gap separation


def test_information_gap_remains_distinct_from_response_gap(
    client: TestClient,
) -> None:
    report = _create_report(client, affected_population=100, source="S1")
    _create_response(client, report["id"])

    coverage = _coverage(client)
    row = coverage["items"][0]
    assert "information_gap_score" not in row
    assert "information_status" not in row
    assert "information_gap" not in " ".join(row.keys())

    gaps = client.get(
        "/api/map/information-gaps",
        params={"cell_size": 0.01},
    ).json()
    for area in gaps["areas"]:
        assert "response_status" not in area
        assert "response_count" not in area

    # The two analyses can disagree without contradicting each other: this
    # needs data is thin but a response is recorded - separate concepts.
    assert row["response_status"] == "RESPONSE_RECORDED"
    assert any(
        area["information_status"] != "SUFFICIENT_INFORMATION"
        for area in gaps["areas"]
    )


def test_coverate_does_not_mutate_source_report(client: TestClient) -> None:
    report = _create_report(
        client,
        evidence=["crowded"],
        needs=("WATER", "FOOD"),
        affected_population=100,
    )
    _create_response(client, report["id"])
    _coverage(client)
    _coverage(client, {"need": "FOOD"})
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["original_text"] == report["original_text"]
    assert stored["needs"] == ["WATER", "FOOD"]
    assert stored["affected_population"] == 100
    assert stored["evidence"] == ["crowded"]


# ---------------------------------------------------------------- OpenAPI


def test_coverage_endpoint_in_openapi(client: TestClient) -> None:
    schema = app.openapi()
    assert "/api/analytics/response-coverage" in schema["paths"]
    operation = schema["paths"]["/api/analytics/response-coverage"]["get"]
    # The responsible-handling distinction must be visible in the docs.
    description = operation.get("description", "")
    assert "NO_RESPONSE_RECORDED" in description
    assert "does NOT mean no response exists" in description
    assert "does not mean nobody is responding" in description.lower() or \
        "not mean nobody is responding" in description.lower()
    schema_names = schema["components"]["schemas"]
    for name in ("CoverageItem", "CoverageResponse", "CoverageStatus"):
        assert name in schema_names, name
    status_enum = schema_names["CoverageStatus"]["enum"]
    assert status_enum == [
        "RESPONSE_RECORDED",
        "NO_RESPONSE_RECORDED",
        "PARTIAL_RESPONSE_RECORDED",
        "UNKNOWN",
    ]
    # The filter model is inlined as query parameters (the established
    # map/search convention), not registered as a component.
    filter_params = {
        parameter["name"]
        for parameter in operation["parameters"]
    }
    for expected in ("need", "report_id", "priority", "verification_status"):
        assert expected in filter_params, expected