import pytest
from fastapi.testclient import TestClient

from app.api.duplicates import get_duplicate_service
from app.api.reports import get_report_service
from app.duplicates.service import DuplicateDetectionService
from app.main import app
from app.repositories import InMemoryReportRepository
from app.services.report_service import ReportService

BASE_TIME = "2026-09-18T10:00:00Z"


@pytest.fixture()
def client():
    """Share ONE repository between report creation and duplicate detection."""
    repository = InMemoryReportRepository()
    app.dependency_overrides[get_report_service] = lambda: ReportService(repository)
    app.dependency_overrides[get_duplicate_service] = (
        lambda: DuplicateDetectionService(repository)
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "500 families need clean drinking water",
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
    response = client.post(f"/api/reports/{report_id}/duplicates")
    assert response.status_code == 200, response.text
    return response.json()


def _related_ids(payload: dict) -> list[str]:
    return [p["related_report_id"] for p in payload["potential_duplicates"]]


def test_two_clearly_similar_reports_detected(client: TestClient) -> None:
    report_a = _create(client, original_text="500 families need clean drinking water after flooding")
    report_b = _create(
        client,
        original_text="Around 500 families need clean drinking water after the flood",
        timestamp="2026-09-18T12:00:00Z",
    )
    result = _detect(client, report_a["id"])
    related = _related_ids(result)
    assert report_b["id"] in related
    match = next(p for p in result["potential_duplicates"] if p["related_report_id"] == report_b["id"])
    assert match["relation"] == "POTENTIAL_DUPLICATE"
    assert match["similarity_score"] >= 0.55
    assert match["matching_factors"]


def test_two_clearly_different_reports_not_detected(client: TestClient) -> None:
    report_a = _create(client, original_text="Flooding damaged riverside homes", incident="Flood")
    report_b = _create(
        client,
        original_text="An earthquake destroyed mountain village schools",
        location="Mountain Village",
        incident="Earthquake",
        timestamp="2026-10-01T08:00:00Z",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_duplicates"] == []
    assert report_b["id"] not in _related_ids(result)


def test_same_location_time_and_incident_detected(client: TestClient) -> None:
    report_a = _create(client, incident="Flood", timestamp=BASE_TIME)
    report_b = _create(client, incident="flooding", timestamp=BASE_TIME)
    result = _detect(client, report_a["id"])
    assert report_b["id"] in _related_ids(result)


def test_same_location_but_different_incidents_not_detected(client: TestClient) -> None:
    report_a = _create(client, original_text="Flood damaged the market", incident="Flood")
    report_b = _create(
        client,
        original_text="Fire destroyed the market",
        incident="Fire",
        timestamp="2026-08-01T08:00:00Z",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_duplicates"] == []


def test_same_need_but_different_incidents_not_detected(client: TestClient) -> None:
    report_a = _create(client, needs=["FOOD"], incident="Flood", location="Village A")
    report_b = _create(
        client,
        original_text="People need food after the earthquake",
        needs=["FOOD"],
        incident="Earthquake",
        location="Village B",
        timestamp="2026-08-02T08:00:00Z",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_duplicates"] == []


def test_different_locations_not_detected_even_with_same_incident(client: TestClient) -> None:
    report_a = _create(
        client,
        original_text="Flooding has damaged homes in Village A",
        incident="Flooding",
        location="Village A",
    )
    report_b = _create(
        client,
        original_text="Flooding has damaged homes in Village B",
        incident="Flooding",
        location="Village B",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_duplicates"] == []


def test_missing_location_still_detected_via_other_factors(client: TestClient) -> None:
    report_a = _create(client, original_text="Flooding has damaged homes near the river", location=None)
    report_b = _create(
        client,
        original_text="Several houses near the river are flooded",
        location=None,
    )
    result = _detect(client, report_a["id"])
    assert report_b["id"] in _related_ids(result)


def test_uncertain_location_not_treated_as_match(client: TestClient) -> None:
    report_a = _create(
        client,
        original_text="Flooding has damaged homes near the river",
        location="somewhere north",
        location_status="UNCERTAIN",
    )
    report_b = _create(
        client,
        original_text="Several houses near the river are flooded",
        location="Riverside",
        location_status="CONFIRMED",
    )
    result = _detect(client, report_a["id"])
    match = next(
        (p for p in result["potential_duplicates"] if p["related_report_id"] == report_b["id"]),
        None,
    )
    assert match is not None
    assert "LOCATION" not in match["matching_factors"]


def test_missing_timestamp_still_works(client: TestClient) -> None:
    report_a = _create(client, timestamp=None)
    report_b = _create(client, timestamp=None)
    result = _detect(client, report_a["id"])
    assert report_b["id"] in _related_ids(result)


def test_missing_needs_still_works(client: TestClient) -> None:
    report_a = _create(client, needs=[])
    report_b = _create(client, needs=[])
    result = _detect(client, report_a["id"])
    assert report_b["id"] in _related_ids(result)


def test_missing_incident_still_works(client: TestClient) -> None:
    report_a = _create(client, incident=None)
    report_b = _create(client, incident=None)
    result = _detect(client, report_a["id"])
    assert report_b["id"] in _related_ids(result)


def test_very_similar_report_text_detected_without_other_signals(client: TestClient) -> None:
    text = "Flooding has damaged homes near the river and shelters are full"
    report_a = _create(client, original_text=text, incident="Flood", location=None)
    report_b = _create(
        client,
        original_text=text + ".",
        incident="Earthquake",
        location=None,
        timestamp="2026-08-03T08:00:00Z",
    )
    result = _detect(client, report_a["id"])
    assert report_b["id"] in _related_ids(result)


def test_different_report_text_not_detected(client: TestClient) -> None:
    report_a = _create(client, original_text="Flood damaged the market and shops")
    report_b = _create(
        client,
        original_text="Teachers need laptops for the school computer lab",
        incident="Education",
        timestamp="2026-08-04T08:00:00Z",
    )
    result = _detect(client, report_a["id"])
    assert result["potential_duplicates"] == []


def test_report_not_compared_with_itself(client: TestClient) -> None:
    report_a = _create(client)
    result = _detect(client, report_a["id"])
    assert result["potential_duplicates"] == []
    assert report_a["id"] not in _related_ids(result)


def test_nonexistent_report_returns_404(client: TestClient) -> None:
    response = client.post("/api/reports/does-not-exist/duplicates")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_no_potential_duplicates_returns_empty_list(client: TestClient) -> None:
    report_a = _create(client)
    _create(
        client,
        original_text="An earthquake destroyed mountain village schools",
        location="Mountain Village",
        incident="Earthquake",
        timestamp="2026-10-01T08:00:00Z",
    )
    result = _detect(client, report_a["id"])
    assert result["report_id"] == report_a["id"]
    assert result["potential_duplicates"] == []


def test_multiple_potential_duplicates_returned_sorted(client: TestClient) -> None:
    report_a = _create(client, original_text="500 families need clean drinking water after flooding")
    report_b = _create(
        client,
        original_text="About 500 families need clean water now",
        timestamp="2026-09-18T12:00:00Z",
    )
    report_c = _create(
        client,
        original_text="Families need drinking water",
        timestamp="2026-09-19T12:00:00Z",
    )
    result = _detect(client, report_a["id"])
    related = _related_ids(result)
    assert report_b["id"] in related
    assert report_c["id"] in related
    scores = [p["similarity_score"] for p in result["potential_duplicates"]]
    assert scores == sorted(scores, reverse=True)


def test_reports_remain_unchanged_after_detection(client: TestClient) -> None:
    before = _create(client, original_text="500 families need clean drinking water")
    _create(client, original_text="Around 500 families need clean drinking water")
    result = _detect(client, before["id"])
    assert result["potential_duplicates"]
    after = client.get(f"/api/reports/{before['id']}").json()
    assert after["original_text"] == before["original_text"]
    assert after == before


def test_reports_are_not_merged(client: TestClient) -> None:
    report_a = _create(client, original_text="500 families need clean drinking water")
    report_b = _create(client, original_text="Around 500 families need clean drinking water")
    _detect(client, report_a["id"])
    all_reports = client.get("/api/reports").json()
    ids = {r["id"] for r in all_reports}
    assert report_a["id"] in ids
    assert report_b["id"] in ids
    assert len(all_reports) == 2


def test_reports_are_not_deleted(client: TestClient) -> None:
    report_a = _create(client, original_text="500 families need clean drinking water")
    report_b = _create(client, original_text="Around 500 families need clean drinking water")
    _detect(client, report_a["id"])
    assert client.get(f"/api/reports/{report_a['id']}").status_code == 200
    assert client.get(f"/api/reports/{report_b['id']}").status_code == 200


def test_endpoint_is_registered_in_openapi(client: TestClient) -> None:
    paths = app.openapi()["paths"]
    assert "/api/reports/{report_id}/duplicates" in paths