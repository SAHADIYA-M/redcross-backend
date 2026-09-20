"""Phase 10 tests: Search & Filter API.

Covers text search, every filter, combined filters, sorting, pagination,
validation errors, uncertainty preservation, traceability, and the
"no matches implies no need" distinction. No AI/external services are used.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.conflicts import get_conflict_service
from app.api.duplicates import get_duplicate_service
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.api.search import get_search_service
from app.api.verification import get_audit_repository, get_verification_service
from app.conflicts.service import ConflictDetectionService
from app.duplicates.service import DuplicateDetectionService
from app.location.providers import StubGeocoder
from app.location.service import LocationService
from app.main import app
from app.repositories import InMemoryReportRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.search.service import SearchService
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.verification.service import VerificationService

BASE_TIME = "2026-09-20T10:00:00Z"


@pytest.fixture()
def client():
    """Give every test a clean, isolated in-memory storage set.

    Search runs against the same shared repositories as the reports API, with
    the Phase 8 priority service wired in, so priority filters and sort by
    priority produce the same numbers as POST /priority.
    """
    report_repository = InMemoryReportRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()

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
    app.dependency_overrides[get_duplicate_service] = (
        lambda: DuplicateDetectionService(report_repository)
    )
    app.dependency_overrides[get_conflict_service] = (
        lambda: ConflictDetectionService(report_repository)
    )
    app.dependency_overrides[get_search_service] = (
        lambda: SearchService(
            report_repository,
            PriorityService(report_repository),
            LocationService(StubGeocoder()),
        )
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def client_without_geocoder():
    """Search with no location service configured (bbox must 503)."""
    report_repository = InMemoryReportRepository()
    app.dependency_overrides[get_report_service] = (
        lambda: ReportService(report_repository)
    )
    app.dependency_overrides[get_search_service] = (
        lambda: SearchService(report_repository, PriorityService(report_repository))
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "No drinking water for the children",
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "incident": "Flood",
        "timestamp": BASE_TIME,
        "source": "FIELD_REPORT",
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _seed(client: TestClient) -> dict:
    """Three baseline reports with distinct fields.

    A -> WATER need, MEDIUM priority (53.5), CONFIRMED kozhikode beach.
    B -> FOOD+SHELTER needs, HIGH priority (83.75), CONFIRMED old bus stand.
    C -> HEALTHCARE need, no priority data (UNKNOWN), UNCERTAIN "market".
    """
    a = _create(
        client,
        needs=["WATER"],
        severity="HIGH",
        affected_population=300,
        location_status="CONFIRMED",
        timestamp="2026-09-20T10:00:00Z",
    )
    b = _create(
        client,
        original_text="Food and shelter urgently needed at the old bus stand",
        incident="Cyclone",
        location="old bus stand",
        needs=["FOOD", "SHELTER"],
        source="PARTNER",
        severity="CRITICAL",
        affected_population=5000,
        vulnerability=["children"],
        time_sensitivity="within 24 hours",
        evidence=["crowded"],
        location_status="CONFIRMED",
        timestamp="2026-09-19T10:00:00Z",
    )
    c = _create(
        client,
        original_text="Medical equipment status unknown in the market area",
        incident="Cyclone",
        location="market",
        needs=["HEALTHCARE"],
        source="OFFICIAL",
        location_status="UNCERTAIN",
        timestamp="2026-09-18T10:00:00Z",
    )
    return {"a": a, "b": b, "c": c}


def _search(client: TestClient, params) -> dict:
    response = client.get("/api/search/reports", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(result: dict) -> set[str]:
    return {item["report_id"] for item in result["items"]}


# ---------------------------------------------------------------- text search


def test_search_by_text(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, {"q": "drinking water"})
    assert _ids(result) == {seed["a"]["id"]}


def test_text_search_is_case_insensitive(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, {"q": "DRINKING WATER"})
    assert _ids(result) == {seed["a"]["id"]}


def test_text_search_with_no_matches_returns_empty(client: TestClient) -> None:
    result = _search(client, {"q": "no such phrase anywhere"})
    assert result["items"] == []
    assert result["total"] == 0


# ------------------------------------------------------------------- filters


def test_filter_by_need_category(client: TestClient) -> None:
    seed = _seed(client)
    assert _ids(_search(client, {"need": "WATER"})) == {seed["a"]["id"]}
    assert _ids(_search(client, {"need": "FOOD"})) == {seed["b"]["id"]}
    assert _ids(_search(client, {"need": "HEALTHCARE"})) == {seed["c"]["id"]}
    assert _ids(_search(client, {"need": "SHELTER"})) == {seed["b"]["id"]}


def test_filter_by_multiple_needs_is_any_match(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, [("need", "HEALTHCARE"), ("need", "WATER")])
    assert _ids(result) == {seed["a"]["id"], seed["c"]["id"]}


def test_filter_by_priority_level(client: TestClient) -> None:
    seed = _seed(client)
    assert _ids(_search(client, {"priority": "MEDIUM"})) == {seed["a"]["id"]}
    assert _ids(_search(client, {"priority": "HIGH"})) == {seed["b"]["id"]}
    assert _ids(_search(client, {"priority": "LOW"})) == set()


def test_filter_by_priority_score_range(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, {"min_priority_score": 60})
    assert _ids(result) == {seed["b"]["id"]}
    result = _search(client, {"max_priority_score": 60})
    assert _ids(result) == {seed["a"]["id"]}
    result = _search(client, {"min_priority_score": 50, "max_priority_score": 60})
    assert _ids(result) == {seed["a"]["id"]}


def test_filter_by_verification_status(client: TestClient) -> None:
    seed = _seed(client)
    client.patch(
        f"/api/reports/{seed['a']['id']}/verify",
        json={"action": "APPROVE", "reason": "confirmed by coordinator"},
    )
    result = _search(client, {"verification_status": "VERIFIED"})
    assert _ids(result) == {seed["a"]["id"]}
    result = _search(client, {"verification_status": "UNVERIFIED"})
    assert _ids(result) == {seed["b"]["id"], seed["c"]["id"]}


def test_filter_by_report_status(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, {"status": "IN_REVIEW"})
    assert result["total"] == 0
    client.patch(f"/api/reports/{seed['c']['id']}", json={"status": "IN_REVIEW"})
    result = _search(client, {"status": "IN_REVIEW"})
    assert _ids(result) == {seed["c"]["id"]}
    result = _search(client, {"status": "RECEIVED"})
    assert _ids(result) == {seed["a"]["id"], seed["b"]["id"]}


def test_filter_by_source(client: TestClient) -> None:
    seed = _seed(client)
    assert _ids(_search(client, {"source": "PARTNER"})) == {seed["b"]["id"]}
    assert _ids(_search(client, {"source": "official"})) == {seed["c"]["id"]}
    assert _ids(_search(client, {"source": "report"})) == {seed["a"]["id"]}


def test_filter_by_incident(client: TestClient) -> None:
    seed = _seed(client)
    assert _ids(_search(client, {"incident": "Flood"})) == {seed["a"]["id"]}
    assert _ids(_search(client, {"incident": "cyclone"})) == {
        seed["b"]["id"],
        seed["c"]["id"],
    }


def test_filter_by_time_range(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(
        client,
        {
            "start_time": "2026-09-20T00:00:00Z",
            "end_time": "2026-09-20T23:59:59Z",
        },
    )
    assert _ids(result) == {seed["a"]["id"]}
    result = _search(
        client,
        {"start_time": "2026-09-19T00:00:00Z", "end_time": "2026-09-19T23:59:59Z"},
    )
    assert _ids(result) == {seed["b"]["id"]}


def test_time_range_bounds_are_inclusive(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(
        client,
        {
            "start_time": "2026-09-18T00:00:00Z",
            "end_time": "2026-09-18T23:59:59Z",
        },
    )
    # the 09-18T10:00Z report is inside; the 19th/20th are outside
    assert _ids(result) == {seed["c"]["id"]}


def test_filter_by_time_range_with_timezone_aware_dates(client: TestClient) -> None:
    seed = _seed(client)
    # 10:00 UTC == 11:30+01:30; boundary is the same instant in either tz
    result = _search(client, {"start_time": "2026-09-20T11:30:00+01:30"})
    assert _ids(result) == {seed["a"]["id"]}


def test_filter_by_naive_datetime_treated_as_utc(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, {"start_time": "2026-09-20T10:00:00"})
    assert _ids(result) == {seed["a"]["id"]}


def test_filter_by_location_text(client: TestClient) -> None:
    seed = _seed(client)
    assert _ids(_search(client, {"location": "beach"})) == {seed["a"]["id"]}
    assert _ids(_search(client, {"location": "bus stand"})) == {seed["b"]["id"]}


def test_filter_by_location_status(client: TestClient) -> None:
    seed = _seed(client)
    assert _ids(_search(client, {"location_status": "CONFIRMED"})) == {
        seed["a"]["id"],
        seed["b"]["id"],
    }
    assert _ids(_search(client, {"location_status": "UNCERTAIN"})) == {
        seed["c"]["id"]
    }


def test_filter_by_bounding_box(client: TestClient) -> None:
    seed = _seed(client)
    # kozhikode beach (11.2588, 75.7804) inside this box
    result = _search(
        client,
        {"min_lat": 11.25, "max_lat": 11.27, "min_lon": 75.77, "max_lon": 75.79},
    )
    assert _ids(result) == {seed["a"]["id"]}
    # old bus stand (11.2602, 75.7620) inside this box
    result = _search(
        client,
        {"min_lat": 11.26, "max_lat": 11.27, "min_lon": 75.76, "max_lon": 75.77},
    )
    assert _ids(result) == {seed["b"]["id"]}


def test_bounding_box_never_matches_uncertain_location(client: TestClient) -> None:
    seed = _seed(client)
    # "market" is ambiguous within the whole gazetteer: never exact, so the box
    # around its candidates still cannot match the UNCERTAIN report.
    result = _search(
        client,
        {"min_lat": 11.25, "max_lat": 11.27, "min_lon": 75.77, "max_lon": 75.79},
    )
    assert seed["c"]["id"] not in _ids(result)


# ---------------------------------------------------------- combined filters


def test_multiple_filters_combined(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(
        client,
        [
            ("need", "WATER"),
            ("priority", "MEDIUM"),
            ("verification_status", "UNVERIFIED"),
            ("source", "FIELD_REPORT"),
            ("start_time", "2026-09-20T00:00:00Z"),
            ("end_time", "2026-09-20T23:59:59Z"),
        ],
    )
    assert _ids(result) == {seed["a"]["id"]}
    # relaxing any condition widens the result correctly (AND semantics)
    result = _search(
        client,
        [("priority", "MEDIUM"), ("start_time", "2026-09-20T00:00:00Z")],
    )
    assert _ids(result) == {seed["a"]["id"]}


# ------------------------------------------------------------------- sorting


def test_sort_by_priority_desc_puts_unknown_last(client: TestClient) -> None:
    _seed(client)
    items = _search(client, {"sort_by": "priority", "sort_order": "desc"})["items"]
    assert [i["priority_score"] for i in items] == [83.75, 53.5, None]
    items = _search(client, {"sort_by": "priority"})["items"]
    assert [i["priority_score"] for i in items] == [83.75, 53.5, None]


def test_sort_by_priority_asc(client: TestClient) -> None:
    _seed(client)
    items = _search(
        client, {"sort_by": "priority", "sort_order": "asc"}
    )["items"]
    assert [i["priority_score"] for i in items] == [53.5, 83.75, None]


def test_sort_by_timestamp_desc_is_default(client: TestClient) -> None:
    seed = _seed(client)
    items = _search(client, {})["items"]
    assert [i["report_id"] for i in items] == [
        seed["a"]["id"],
        seed["b"]["id"],
        seed["c"]["id"],
    ]


def test_sort_by_timestamp_asc(client: TestClient) -> None:
    seed = _seed(client)
    items = _search(client, {"sort_by": "timestamp", "sort_order": "asc"})["items"]
    assert [i["report_id"] for i in items] == [
        seed["c"]["id"],
        seed["b"]["id"],
        seed["a"]["id"],
    ]


def test_sort_by_affected_population(client: TestClient) -> None:
    seed = _seed(client)
    items = _search(
        client, {"sort_by": "affected_population", "sort_order": "desc"}
    )["items"]
    assert [i["report_id"] for i in items] == [
        seed["b"]["id"],
        seed["a"]["id"],
        seed["c"]["id"],
    ]


# ---------------------------------------------------------------- pagination


def test_pagination(client: TestClient) -> None:
    seed = _seed(client)
    first = _search(client, {"page_size": 2, "page": 1})
    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert first["page"] == 1
    assert first["page_size"] == 2
    second = _search(client, {"page_size": 2, "page": 2})
    assert len(second["items"]) == 1
    assert second["items"][0]["report_id"] == seed["c"]["id"]
    assert first["total"] == second["total"]


def test_pagination_out_of_range_page_returns_empty_items(client: TestClient) -> None:
    _seed(client)
    result = _search(client, {"page": 10, "page_size": 5})
    assert result["items"] == []
    assert result["total"] == 3


# ------------------------------------------------------------ error handling


def test_invalid_need_category_returns_422(client: TestClient) -> None:
    response = client.get("/api/search/reports", params={"need": "BOGUS"})
    assert response.status_code == 422


def test_invalid_priority_returns_422(client: TestClient) -> None:
    response = client.get("/api/search/reports", params={"priority": "TURBO"})
    assert response.status_code == 422


def test_invalid_verification_status_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/search/reports", params={"verification_status": "NOPE"}
    )
    assert response.status_code == 422


def test_invalid_report_status_returns_422(client: TestClient) -> None:
    response = client.get("/api/search/reports", params={"status": "MAYBE"})
    assert response.status_code == 422


def test_inverted_date_range_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/search/reports",
        params={
            "start_time": "2026-01-02T00:00:00Z",
            "end_time": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


def test_out_of_range_coordinates_returns_422(client: TestClient) -> None:
    response = client.get("/api/search/reports", params={"min_lat": 95})
    assert response.status_code == 422
    response = client.get("/api/search/reports", params={"max_lon": 200})
    assert response.status_code == 422


def test_inverted_bounding_box_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/search/reports",
        params={"min_lat": 11.3, "max_lat": 11.2, "min_lon": 75.7, "max_lon": 75.8},
    )
    assert response.status_code == 422


def test_partial_bounding_box_returns_422(client: TestClient) -> None:
    response = client.get("/api/search/reports", params={"min_lat": 11.2, "max_lat": 11.3})
    assert response.status_code == 422


def test_invalid_sort_field_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/search/reports", params={"sort_by": "__class__"}
    )
    assert response.status_code == 422


def test_invalid_sort_order_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/search/reports", params={"sort_order": "sideways"}
    )
    assert response.status_code == 422


def test_invalid_priority_score_range_returns_422(client: TestClient) -> None:
    response = client.get("/api/search/reports", params={"min_priority_score": 80, "max_priority_score": 10})
    assert response.status_code == 422
    response = client.get("/api/search/reports", params={"min_priority_score": 120})
    assert response.status_code == 422


def test_invalid_pagination_returns_422(client: TestClient) -> None:
    assert client.get("/api/search/reports", params={"page": 0}).status_code == 422
    assert client.get("/api/search/reports", params={"page_size": 0}).status_code == 422
    assert client.get("/api/search/reports", params={"page_size": 101}).status_code == 422
    assert client.get("/api/search/reports", params={"page_size": "abc"}).status_code == 422


def test_bbox_without_geocoder_returns_503(client_without_geocoder: TestClient) -> None:
    client_without_geocoder.post(
        "/api/reports",
        json={"original_text": "flood at the beach", "reporter": "t"},
    )
    response = client_without_geocoder.get(
        "/api/search/reports",
        params={"min_lat": 11.2, "max_lat": 11.3, "min_lon": 75.7, "max_lon": 75.8},
    )
    assert response.status_code == 503
    assert "location service" in response.json()["detail"].lower()


# --------------------------------------------------------------- uncertainty


def test_unknown_priority_stays_unknown_not_low(client: TestClient) -> None:
    seed = _seed(client)
    # C has no usable priority data: it must not be reportable as LOW.
    assert _ids(_search(client, {"priority": "LOW"})) == set()
    result = _search(client, {"q": "Medical"})
    item = next(i for i in result["items"] if i["report_id"] == seed["c"]["id"])
    assert item["priority_level"] is None
    assert item["priority_score"] is None


def test_uncertain_verification_stays_uncertain(client: TestClient) -> None:
    seed = _seed(client)
    client.patch(
        f"/api/reports/{seed['c']['id']}/verify",
        json={"action": "MARK_UNCERTAIN", "reason": "cannot confirm"},
    )
    result = _search(client, {"verification_status": "UNCERTAIN"})
    assert _ids(result) == {seed["c"]["id"]}
    item = result["items"][0]
    assert item["verification_status"] == "UNCERTAIN"


def test_unverified_report_is_not_verified(client: TestClient) -> None:
    seed = _seed(client)
    # no verification record exists -> UNVERIFIED, never VERIFIED
    assert _ids(_search(client, {"verification_status": "VERIFIED"})) == set()
    assert _ids(_search(client, {"verification_status": "UNVERIFIED"})) == {
        seed["a"]["id"],
        seed["b"]["id"],
        seed["c"]["id"],
    }


def test_uncertain_location_kept_marked_in_results(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, {"q": "Medical"})
    item = next(i for i in result["items"] if i["report_id"] == seed["c"]["id"])
    assert item["location_status"] == "UNCERTAIN"


# -------------------------------------------------------------- traceability


def test_original_report_text_is_never_modified_by_search(client: TestClient) -> None:
    seed = _seed(client)
    _search(client, {"q": "drinking water"})
    _search(client, {"sort_by": "affected_population", "sort_order": "desc"})
    for report in seed.values():
        stored = client.get(f"/api/reports/{report['id']}").json()
        assert stored["original_text"] == report["original_text"]


def test_search_results_preserve_traceability(client: TestClient) -> None:
    seed = _seed(client)
    result = _search(client, {})
    by_id = {item["report_id"]: item for item in result["items"]}
    for _, report in seed.items():
        item = by_id[report["id"]]
        assert item["source"] == report["source"]
        assert item["timestamp"] == report["timestamp"]
        assert item["location"] == report["location"]
        assert item["incident"] == report["incident"]
        assert item["verification_status"] == report["verification_status"]


def test_empty_results_do_not_imply_zero_need(client: TestClient) -> None:
    _seed(client)
    result = _search(client, {"q": "unrelated topic"})
    # The response is a plain empty page with metadata; it says nothing about
    # whether humanitarian need exists.
    assert result["items"] == []
    assert result["total"] == 0
    assert result["page"] == 1
    assert result["page_size"] == 20


def test_search_result_item_contains_dashboard_fields(client: TestClient) -> None:
    seed = _seed(client)
    items = _search(client, {"q": "Food"})["items"]
    assert len(items) == 1
    item = items[0]
    assert item["report_id"] == seed["b"]["id"]
    assert item["original_text"] == seed["b"]["original_text"]
    assert item["needs"] == ["FOOD", "SHELTER"]
    assert item["priority_level"] == "HIGH"
    assert item["priority_score"] == 83.75
    assert item["status"] == "RECEIVED"
    assert item["affected_population"] == 5000


# ------------------------------------------------------------------- OpenAPI


def test_search_endpoint_in_openapi(client: TestClient) -> None:
    schema = app.openapi()
    assert "/api/search/reports" in schema["paths"]
    assert "get" in schema["paths"]["/api/search/reports"]
    parameters = schema["paths"]["/api/search/reports"]["get"]["parameters"]
    names = {parameter["name"] for parameter in parameters}
    for expected in (
        "q",
        "need",
        "priority",
        "min_priority_score",
        "verification_status",
        "status",
        "location",
        "location_status",
        "min_lat",
        "min_lon",
        "start_time",
        "end_time",
        "incident",
        "source",
        "sort_by",
        "sort_order",
        "page",
        "page_size",
    ):
        assert expected in names, expected