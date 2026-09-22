"""Batch 3: map endpoints must surface geocoder failures as a consistent 503,
never a 500 that leaks provider internals.

Covers /api/map/reports, /api/map/information-gaps and /api/map/responses,
and the /api/search/reports geocoder path.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.map import (
    get_information_gap_service as get_map_gap_service,
    get_map_service,
)
from app.api.map_responses import get_response_map_service
from app.location.errors import GeocoderUnavailableError
from app.main import app

GEOCODER_DOWN = "Geocoder temporarily unavailable"


class _BrokenGeocoderService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def map_reports(self, params):
        raise self._error

    def analyze(self, params):
        raise self._error

    def map_responses(self, params):
        raise self._error


@pytest.fixture()
def client(auth_setup, admin_headers) -> TestClient:
    with TestClient(app) as test_client:
        test_client.headers.update(admin_headers)
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "path,dep",
    [
        ("/api/map/reports", get_map_service),
        ("/api/map/information-gaps", get_map_gap_service),
        ("/api/map/responses", get_response_map_service),
    ],
)
def test_geocoder_failure_is_consistent_503(client: TestClient, path: str, dep) -> None:
    app.dependency_overrides[dep] = lambda: _BrokenGeocoderService(
        GeocoderUnavailableError("upstream down")
    )
    response = client.get(path)
    assert response.status_code == 503, (path, response.text)
    assert response.json()["detail"] == GEOCODER_DOWN


def test_search_geocoder_failure_is_consistent_503(
    client: TestClient,
) -> None:
    from app.api.search import get_search_service

    # /api/search already maps LocationError -> 503; assert the message shape
    # matches the map endpoints for uniformity.
    class _BrokenSearch:
        def search(self, params):
            raise GeocoderUnavailableError("upstream down")

    app.dependency_overrides[get_search_service] = lambda: _BrokenSearch()
    response = client.get("/api/search/reports", params={"q": "water"})
    assert response.status_code == 503
    assert response.json()["detail"] == GEOCODER_DOWN