"""Phase 10 regression tests: priority is computed exactly once per request.

Locks in the audit fix that removed double priority computation in search and
map. A score for a report must be calculated at most once per request (and
only for reports that can actually carry one), then reused for filtering,
sorting and output.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.ai.schemas import NeedCategory, SeverityLevel
from app.api.map import get_map_service
from app.api.search import get_search_service
from app.location.providers import StubGeocoder
from app.location.service import LocationService
from app.main import app
from app.models.report import Report
from app.repositories import InMemoryReportRepository
from app.search.service import SearchService
from app.services.map_service import MapService
from app.services.priority_service import PriorityService


class _CountingPriorityService(PriorityService):
    """PriorityService that records how many times a score is calculated."""

    def __init__(self, repository: InMemoryReportRepository) -> None:
        super().__init__(repository)
        self.calls = 0

    def calculate_for_report(self, report_id: str):
        self.calls += 1
        return super().calculate_for_report(report_id)


def _report(
    report_id: str,
    text: str,
    *,
    with_signal: bool,
) -> Report:
    kwargs = (
        {
            "severity": SeverityLevel.HIGH,
            "affected_population": 500,
            "vulnerability": ["children"],
            "time_sensitivity": "within 24 hours",
            "evidence": ["no clean drinking water"],
        }
        if with_signal
        else {}
    )
    return Report(
        id=report_id,
        original_text=text,
        reporter="reporter",
        timestamp=datetime(2026, 9, 20, tzinfo=timezone.utc),
        location="kozhikode beach",
        incident="Flood",
        needs=[NeedCategory.WATER],
        source="field",
        **kwargs,
    )


@pytest.fixture()
def priority_client(admin_headers):
    """Live app whose search/map services share a counting priority service."""
    reports = InMemoryReportRepository()
    reports.create(_report("r1", "river flooded the market", with_signal=True))
    reports.create(_report("r2", "families stranded by flooding", with_signal=True))
    reports.create(_report("r3", "road blocked", with_signal=False))

    counting = _CountingPriorityService(reports)
    location = LocationService(StubGeocoder())
    search = SearchService(reports, counting, location)

    app.dependency_overrides[get_search_service] = lambda: search
    app.dependency_overrides[get_map_service] = (
        lambda: MapService(SearchService(reports, counting, location), location)
    )

    with TestClient(app) as client:
        client.headers.update(admin_headers)
        yield client, counting
    app.dependency_overrides.clear()


def test_priority_computed_once_per_report_per_search(priority_client):
    client, counting = priority_client

    response = client.get(
        "/api/search/reports",
        params={"sort_by": "priority", "priority": "HIGH", "page_size": 100},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["priority_level"] == "HIGH"
    # Exactly the two signal-carrying reports, each scored once.
    assert counting.calls == 2


def test_priority_not_computed_for_reports_without_signal(priority_client):
    client, counting = priority_client

    response = client.get("/api/search/reports", params={"page_size": 100})
    assert response.status_code == 200
    assert response.json()["total"] == 3
    # The no-signal report is never scored; the two signal reports scored once.
    assert counting.calls == 2


def test_map_does_not_recompute_priority_from_filter(priority_client):
    client, counting = priority_client

    response = client.get("/api/map/reports", params={"sort_by": "latitude"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    # One score per signal-carrying report for the map request itself.
    assert counting.calls == 2