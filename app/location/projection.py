"""Geographic projection helpers shared by map and feature services.

Coordinate rules shared by every layer that places data on a map:
- a location becomes a point ONLY when it geocodes to CONFIRMED with in-range
  coordinates that are NOT the 0,0 "null island" fallback (0,0 is the Gulf of
  Guinea, commonly used as a missing-value placeholder and must never be
  rendered as a genuine location);
- UNCERTAIN, ambiguous or missing locations are never placed anywhere;
- location confidence is whatever the provider actually returned (None when it
  returned none - never invented).
"""

from app.location.schemas import LocationStatus
from app.location.service import LocationService

NULL_ISLAND_LATITUDE = 0.0
NULL_ISLAND_LONGITUDE = 0.0


def is_null_island(latitude: float | None, longitude: float | None) -> bool:
    """True when the coordinates are the 0,0 fallback.

    0,0 points to a real location in the Gulf of Guinea and is commonly used
    as a "missing value" placeholder; it must never be rendered as a genuine
    report location.
    """
    return (
        latitude == NULL_ISLAND_LATITUDE
        and longitude == NULL_ISLAND_LONGITUDE
    )


def resolve_confirmed_point(
    location: str | None,
    location_service: LocationService,
) -> tuple[float, float, float | None] | None:
    """Geocode ``location`` and return (lat, lng, confidence) only when confirmed.

    Returns None when the location is missing, ambiguous, unresolvable, or maps
    to the 0,0 null-island fallback. Never invents coordinates.
    """
    if location is None or not location.strip():
        return None
    result = location_service.geocode(location)
    if (
        result.status != LocationStatus.CONFIRMED
        or result.latitude is None
        or result.longitude is None
    ):
        return None
    if is_null_island(result.latitude, result.longitude):
        return None
    return result.latitude, result.longitude, result.confidence