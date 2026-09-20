from pydantic import ValidationError

from app.location.errors import (
    GeocoderInvalidResponseError,
    GeocoderUnavailableError,
)
from app.location.geocoder import Geocoder
from app.location.schemas import GeocodeMatch, LocationResult, LocationStatus
from app.location import errors as location_errors


class LocationService:
    """Business logic for geocoding and location validation.

    Pipeline: FastAPI route -> LocationService -> Geocoder provider ->
    Pydantic-validated coordinates -> LocationResult.

    The service is responsible for all location business rules:
    - never guess or silently pick an ambiguous location
    - preserve the raw location verbatim
    - map provider confidence/ambiguity into the result status
    - leave missing locations UNCERTAIN instead of inventing them

    Depends only on the Geocoder interface, so the provider can be swapped
    without touching the routes or schemas.

    A single request-scoped instance may geocode the same raw location several
    times (e.g. a bounding-box filter and the projection step both need
    coordinates); results are memoized per instance so the provider is never
    called twice for the same location within one request. Instances are built
    per request by the dependency factories, so the cache never outlives a
    request.
    """

    def __init__(self, geocoder: Geocoder) -> None:
        self._geocoder = geocoder
        self._cache: dict[str, LocationResult] = {}

    def geocode(self, raw_location: str | None) -> LocationResult:
        if raw_location is None or not raw_location.strip():
            return LocationResult(
                raw_location=None,
                source=self._geocoder.source,
                status=LocationStatus.UNCERTAIN,
            )

        raw = raw_location.strip()
        cached = self._cache.get(raw)
        if cached is not None:
            return cached

        result = self._resolve(raw)
        self._cache[raw] = result
        return result

    def _resolve(self, raw: str) -> LocationResult:
        try:
            matches = self._geocoder.geocode(raw)
        except location_errors.LocationError:
            raise
        except Exception as exc:
            raise GeocoderUnavailableError(
                f"Geocoder failed: {exc}"
            ) from exc

        if not matches:
            return LocationResult(
                raw_location=raw,
                source=self._geocoder.source,
                status=LocationStatus.UNCERTAIN,
            )

        # Ambiguity: more than one candidate means we cannot confidently select
        # one. Do NOT guess — mark UNCERTAIN and keep the raw location.
        if len(matches) > 1:
            return LocationResult(
                raw_location=raw,
                source=self._geocoder.source,
                status=LocationStatus.UNCERTAIN,
            )

        match = self._validate_match(matches[0])
        return LocationResult(
            raw_location=raw,
            resolved_location=match.resolved_location,
            latitude=match.latitude,
            longitude=match.longitude,
            confidence=match.confidence,
            source=self._geocoder.source,
            status=LocationStatus.CONFIRMED,
        )

    @staticmethod
    def _validate_match(match: object) -> GeocodeMatch:
        try:
            return GeocodeMatch.model_validate(match)
        except ValidationError as exc:
            raise GeocoderInvalidResponseError(
                "Geocoder returned out-of-range or malformed coordinates."
            ) from exc