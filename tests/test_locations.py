import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.locations import get_location_service
from app.location.errors import (
    GeocoderConfigurationError,
    GeocoderInvalidResponseError,
    GeocoderTimeoutError,
    GeocoderUnavailableError,
)
from app.location.schemas import GeocodeMatch, LocationResult, LocationStatus
from app.location.service import LocationService
from app.main import app
from app.location.providers import StubGeocoder, build_geocoder


class FakeGeocoder:
    """Scriptable Geocoder stand-in that never touches the network."""

    source: str = "fake"

    def __init__(
        self,
        matches: list[GeocodeMatch] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._matches = matches or []
        self._error = error
        self.calls: list[str] = []

    def geocode(self, raw_location: str) -> list[GeocodeMatch]:
        self.calls.append(raw_location)
        if self._error is not None:
            raise self._error
        return self._matches


@pytest.fixture()
def location_client(auth_setup, admin_headers) -> TestClient:
    with TestClient(app) as client:
        client.headers.update(admin_headers)
        yield client
    app.dependency_overrides.clear()


def _override_location_service(client: TestClient, geocoder: object) -> None:
    service = LocationService(geocoder)  # type: ignore[arg-type]
    app.dependency_overrides[get_location_service] = lambda: service


def _single_match() -> GeocodeMatch:
    return GeocodeMatch(
        resolved_location="Kozhikode Beach, Kozhikode, Kerala, India",
        latitude=11.2588,
        longitude=75.7804,
        confidence=0.95,
    )


def test_valid_location_confirmed(location_client: TestClient) -> None:
    _override_location_service(location_client, FakeGeocoder(matches=[_single_match()]))
    response = location_client.post(
        "/api/locations/geocode", json={"raw_location": "Kozhikode Beach"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CONFIRMED"
    assert body["latitude"] == 11.2588
    assert body["longitude"] == 75.7804
    assert body["confidence"] == 0.95
    assert body["source"] == "fake"
    assert body["resolved_location"] == "Kozhikode Beach, Kozhikode, Kerala, India"


def test_successful_geocoding_service_returns_result() -> None:
    service = LocationService(FakeGeocoder(matches=[_single_match()]))
    result = service.geocode("Kozhikode Beach")
    assert isinstance(result, LocationResult)
    assert result.status == LocationStatus.CONFIRMED
    assert result.latitude == 11.2588
    assert result.longitude == 75.7804


def test_missing_location_is_uncertain() -> None:
    service = LocationService(FakeGeocoder(matches=[]))
    result = service.geocode(None)
    assert result.status == LocationStatus.UNCERTAIN
    assert result.raw_location is None
    assert result.latitude is None
    assert result.longitude is None


def test_empty_location_rejected_by_api(location_client: TestClient) -> None:
    _override_location_service(location_client, FakeGeocoder(matches=[]))
    response = location_client.post("/api/locations/geocode", json={"raw_location": ""})
    assert response.status_code == 422


def test_no_geocoding_result_is_uncertain() -> None:
    service = LocationService(FakeGeocoder(matches=[]))
    result = service.geocode("unknown place")
    assert result.status == LocationStatus.UNCERTAIN
    assert result.latitude is None
    assert result.resolved_location is None
    assert result.raw_location == "unknown place"


def test_ambiguous_location_is_uncertain(location_client: TestClient) -> None:
    matches = [
        _single_match(),
        GeocodeMatch(
            resolved_location="Mananchira Market, Kozhikode, Kerala, India",
            latitude=11.2529,
            longitude=75.7807,
            confidence=0.5,
        ),
    ]
    _override_location_service(location_client, FakeGeocoder(matches=matches))
    response = location_client.post(
        "/api/locations/geocode", json={"raw_location": "near the market"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNCERTAIN"
    assert body["resolved_location"] is None
    assert body["latitude"] is None
    assert body["longitude"] is None
    assert body["raw_location"] == "near the market"


def test_stub_geocoder_ambiguity_market_is_uncertain() -> None:
    matches = StubGeocoder().geocode("there is flooding near the market")
    assert len(matches) == 2
    service = LocationService(StubGeocoder())
    result = service.geocode("there is flooding near the market")
    assert result.status == LocationStatus.UNCERTAIN


def test_stub_geocoder_ambiguity_hospital_is_uncertain() -> None:
    matches = StubGeocoder().geocode("the central hospital")
    assert len(matches) == 2
    service = LocationService(StubGeocoder())
    result = service.geocode("the central hospital")
    assert result.status == LocationStatus.UNCERTAIN


def test_invalid_coordinates_rejected() -> None:
    with pytest.raises(ValidationError):
        GeocodeMatch(resolved_location="x", latitude=95.0, longitude=0.0)
    with pytest.raises(ValidationError):
        GeocodeMatch(resolved_location="x", latitude=0.0, longitude=181.0)


def test_out_of_range_coordinates_are_clean_error(location_client: TestClient) -> None:
    class BrokenGeocoder:
        source: str = "broken"

        def geocode(self, raw_location: str) -> list[dict]:
            return [{"resolved_location": "x", "latitude": 200.0, "longitude": 0.0}]

    _override_location_service(location_client, BrokenGeocoder())
    response = location_client.post(
        "/api/locations/geocode", json={"raw_location": "nowhere"}
    )
    assert response.status_code == 502
    assert "200" not in response.json()["detail"]


def test_geocoder_failure_is_clean_error(location_client: TestClient) -> None:
    fake = FakeGeocoder(error=GeocoderUnavailableError("upstream down"))
    _override_location_service(location_client, fake)
    response = location_client.post(
        "/api/locations/geocode", json={"raw_location": "anywhere"}
    )
    assert response.status_code == 502
    assert "upstream down" not in response.json()["detail"]


def test_geocoder_timeout_is_gateway_timeout(location_client: TestClient) -> None:
    fake = FakeGeocoder(error=GeocoderTimeoutError("slow"))
    _override_location_service(location_client, fake)
    response = location_client.post(
        "/api/locations/geocode", json={"raw_location": "anywhere"}
    )
    assert response.status_code == 504


def test_raw_location_preserved(location_client: TestClient) -> None:
    _override_location_service(location_client, FakeGeocoder(matches=[_single_match()]))
    raw = "near the old bus stand in Kozhikode"
    response = location_client.post("/api/locations/geocode", json={"raw_location": raw})
    body = response.json()
    assert body["raw_location"] == raw
    assert "Kozhikode" in body["resolved_location"]


def test_correct_status_present_in_every_case() -> None:
    service = LocationService(FakeGeocoder(matches=[]))
    assert service.geocode("abc").status == LocationStatus.UNCERTAIN
    assert service.geocode(None).status == LocationStatus.UNCERTAIN


def test_coordinate_bounds_in_result_schema() -> None:
    with pytest.raises(ValidationError):
        LocationResult(latitude=91.0, longitude=0.0, source="x", status=LocationStatus.CONFIRMED)
    with pytest.raises(ValidationError):
        LocationResult(latitude=0.0, longitude=-181.0, source="x", status=LocationStatus.CONFIRMED)


def test_build_geocoder_unknown_provider_raises() -> None:
    with pytest.raises(GeocoderConfigurationError):
        build_geocoder("not-a-provider")


def test_build_geocoder_configuration_error_is_503(
    location_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "geocoder_provider", "unknown-provider")
    response = location_client.post("/api/locations/geocode", json={"raw_location": "x"})
    assert response.status_code == 503


def test_endpoint_in_openapi() -> None:
    schema = app.openapi()
    assert "/api/locations/geocode" in schema["paths"]
    assert "GeocodeRequest" in schema["components"]["schemas"]
    response_schema = schema["components"]["schemas"]["GeocodeResponse"]
    for field in (
        "raw_location",
        "resolved_location",
        "latitude",
        "longitude",
        "confidence",
        "source",
        "status",
    ):
        assert field in response_schema["properties"]
    assert "LocationStatus" in schema["components"]["schemas"]


def test_service_wraps_unknown_geocoder_exception() -> None:
    class ExplodingGeocoder:
        source: str = "exploding"

        def geocode(self, raw_location: str) -> list[GeocodeMatch]:
            raise RuntimeError("unexpected internal failure")

    service = LocationService(ExplodingGeocoder())
    with pytest.raises(GeocoderUnavailableError):
        service.geocode("here")


def test_geocoder_invalid_response_rejected() -> None:
    class BadGeocoder:
        source: str = "bad"

        def geocode(self, raw_location: str) -> list[object]:
            return [{"resolved_location": "x", "latitude": 300.0, "longitude": 400.0}]

    service = LocationService(BadGeocoder())
    with pytest.raises(GeocoderInvalidResponseError):
        service.geocode("here")