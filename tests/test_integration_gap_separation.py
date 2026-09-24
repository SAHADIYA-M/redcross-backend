"""Phase 14 separation-of-concepts regression tests.

The API's responsible-data rules must hold across endpoints:
- response coverage NEVER states "nobody is responding" - only what is
  recorded. CANCELLED activities stay traceable but never count.
- an activity without a specific need never counts as coverage for any need.
- information sufficiency is NEVER fused with coverage: gap areas carry no
  coverage fields and coverage rows carry no gap fields, and an area with
  zero reports is INSUFFICIENT_INFORMATION, never "no need".
"""

from fastapi.testclient import TestClient


def _create_report(client: TestClient) -> dict:
    response = client.post(
        "/api/reports",
        json={
            "original_text": (
                "About 500 families near the Kozhikode beach have no clean "
                "drinking water after the flood."
            ),
            "reporter": "field_team_01",
            "location": "kozhikode beach",
            "source": "FIELD_REPORT",
            "needs": ["WATER", "FOOD"],
            "severity": "HIGH",
            "affected_population": 500,
            "evidence": ["no clean drinking water since yesterday"],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_cancelled_only_need_is_no_response_recorded(app_client) -> None:
    report = _create_report(app_client)
    cancelled = app_client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "need": "FOOD",
            "activity": "Ration drop",
            "response_status": "CANCELLED",
            "source": "CDC_NGO",
        },
    )
    assert cancelled.status_code == 201
    cancelled_id = cancelled.json()["response_id"]

    coverage = app_client.get(
        "/api/analytics/response-coverage",
        params={"report_id": report["id"]},
    ).json()
    by_need = {item["need"]: item for item in coverage["items"]}
    food = by_need["FOOD"]
    assert food["response_status"] == "NO_RESPONSE_RECORDED"
    assert food["response_count"] == 0
    assert food["coverage_percentage"] is None
    water = by_need["WATER"]
    assert water["response_status"] == "NO_RESPONSE_RECORDED"
    assert water["response_count"] == 0

    # The cancelled activity is still listed for traceability and its status
    # stays CANCELLED - it is preserved, not deleted, not counted.
    listing = app_client.get(
        "/api/responses", params={"report_id": report["id"]}
    ).json()
    activity = next(
        (a for a in listing if a["response_id"] == cancelled_id), None
    )
    assert activity is not None
    assert activity["response_status"] == "CANCELLED"


def test_general_response_never_counts_for_a_specific_need(app_client) -> None:
    report = _create_report(app_client)
    general = app_client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "activity": "General relief distribution",
            "response_status": "IN_PROGRESS",
            "affected_population": 500,
            "source": "CDC_NGO",
        },
    )
    assert general.status_code == 201

    coverage = app_client.get(
        "/api/analytics/response-coverage",
        params={"report_id": report["id"]},
    ).json()
    by_need = {item["need"]: item for item in coverage["items"]}
    # The need-unspecific activity is not guessed onto WATER or FOOD.
    assert by_need["WATER"]["response_count"] == 0
    assert by_need["FOOD"]["response_count"] == 0
    assert by_need["WATER"]["response_status"] == "NO_RESPONSE_RECORDED"

    # But the general activity itself is still fully visible.
    listing = app_client.get(
        "/api/responses", params={"report_id": report["id"]}
    ).json()
    assert any(a["need"] is None for a in listing)


def test_information_gap_and_coverage_are_never_fused(app_client) -> None:
    report = _create_report(app_client)
    app_client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "need": "WATER",
            "activity": "Delivering bottled water",
            "response_status": "PLANNED",
            "affected_population": 300,
            "source": "CDC_NGO",
        },
    )

    coverage = app_client.get(
        "/api/analytics/response-coverage",
        params={"report_id": report["id"]},
    ).json()
    row = [item for item in coverage["items"] if item["need"] == "WATER"][0]
    # Coverage rows never carry information-sufficiency fields.
    assert "information_gap_score" not in row
    assert "area_id" not in row
    assert "reasons" not in row

    gaps = app_client.get("/api/map/information-gaps").json()
    assert gaps["total"] == 1
    area = gaps["areas"][0]
    # Gap areas never carry coverage fields and never mention responses.
    assert "response_status" not in area
    assert "response_count" not in area
    assert "coverage_percentage" not in area
    assert "need" not in area

    # The gap describes how much we trust our knowledge, not how much is needed.
    assert area["information_status"] == "LIMITED_INFORMATION"
    assert area["report_count"] == 1


def test_zero_reports_is_insufficient_information_never_no_need(
    app_client,
) -> None:
    # A bounding box over an entirely empty area produces an enumerable area,
    # scored as the worst gap - not as "low need" or "nothing needed".
    min_lat = 12.90
    max_lat = 12.95
    min_lon = 74.80
    max_lon = 74.90
    gaps = app_client.get(
        "/api/map/information-gaps",
        params={
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
    ).json()
    assert gaps["total"] >= 1
    empty = [a for a in gaps["areas"] if a["report_count"] == 0]
    assert empty
    for area in empty:
        assert area["information_status"] == "INSUFFICIENT_INFORMATION"
        assert area["information_gap_score"] == 100
        assert any(
            "No reports available" in reason for reason in area["reasons"]
        )


def test_coverage_rows_honour_datetimes_without_inventing_anything(
    app_client,
) -> None:
    """Time-windowed response queries are filters, not statements about need."""
    report = _create_report(app_client)
    app_client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "need": "WATER",
            "activity": "Delivering bottled water",
            "response_status": "PLANNED",
        },
    )
    future = app_client.get(
        "/api/responses",
        params={
            "report_id": report["id"],
            "start_time": "2099-01-01T00:00:00Z",
            "end_time": "2099-12-31T00:00:00Z",
        },
    ).json()
    assert future == []  # an empty window means no activity matches the window