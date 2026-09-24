"""Batch 3: information-gap bounding box must not enumerate an unbounded
number of grid cells.

A bbox spanning a whole state at MIN_CELL_SIZE would generate hundreds of
millions of cells, so the request is rejected with a 422 client error rather
than being silently truncated (truncation could hide information gaps).
"""

import pytest
from fastapi.testclient import TestClient

from app.api.map import get_information_gap_service
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.information_gap.schemas import (
    MAX_INFORMATION_GAP_CELLS,
    overlapping_cell_count,
)
from app.location.providers import StubGeocoder
from app.location.service import LocationService
from app.main import app
from app.repositories import InMemoryReportRepository
from app.services.information_gap_service import (
    InformationGapService,
    cells_overlapping,
)
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService


@pytest.fixture()
def client():
    report_repository = InMemoryReportRepository()
    location_service = LocationService(StubGeocoder())

    app.dependency_overrides[get_report_service] = (
        lambda: ReportService(report_repository)
    )
    app.dependency_overrides[get_priority_service] = (
        lambda: PriorityService(report_repository)
    )
    app.dependency_overrides[get_information_gap_service] = (
        lambda: InformationGapService(
            report_repository,
            location_service,
        )
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_overlapping_cell_count_matches_actual_enumeration() -> None:
    """The validation counter must never disagree with the produced grid."""
    cases = [
        (11.20, 11.30, 75.70, 75.80, 0.01),
        (11.0, 12.0, 75.0, 77.0, 0.05),
        (0.0, 0.5, 0.0, 0.5, 0.25),
        (-1.0, 1.0, -1.0, 1.0, 1.0),
        (11.25, 11.25, 75.78, 75.78, 0.01),
    ]
    for min_lat, max_lat, min_lon, max_lon, size in cases:
        expected = len(
            cells_overlapping(min_lat, max_lat, min_lon, max_lon, size)
        )
        assert (
            overlapping_cell_count(min_lat, max_lat, min_lon, max_lon, size)
            == expected
        ), (min_lat, max_lat, min_lon, max_lon, size)


def test_oversized_bbox_rejected_with_422(client: TestClient) -> None:
    # 10.0 deg x 5.0 deg at 0.01 cell size -> ~500,000 cells >> cap.
    response = client.get(
        "/api/map/information-gaps",
        params={
            "min_lat": 10.0,
            "max_lat": 15.0,
            "min_lon": 72.0,
            "max_lon": 77.0,
            "cell_size": 0.01,
        },
    )
    assert response.status_code == 422
    assert str(MAX_INFORMATION_GAP_CELLS) in str(response.json()["detail"])


def test_box_just_under_cap_ok(client: TestClient) -> None:
    # 0.99 x 0.99 degrees at 0.01 -> 99*99 = 9801 cells < 10,000.
    response = client.get(
        "/api/map/information-gaps",
        params={
            "min_lat": 11.0,
            "max_lat": 11.99,
            "min_lon": 75.0,
            "max_lon": 75.99,
            "cell_size": 0.01,
        },
    )
    assert response.status_code == 200, response.text


def test_no_bbox_unchanged(client: TestClient) -> None:
    response = client.get("/api/map/information-gaps")
    assert response.status_code == 200
    assert response.json()["areas"] == []