"""Shared FastAPI dependencies for geocoder / location service access.

Centralises the two common patterns:
- get_optional_location_service : returns None when the provider is not
  configured; callers handle the absence gracefully.
- get_required_location_service : raises HTTP 503 when the provider is not
  configured; used by map endpoints that cannot function without geocoding.
"""

from fastapi import HTTPException, status

from app.core.config import settings
from app.location.errors import GeocoderConfigurationError
from app.location.providers import build_geocoder
from app.location.service import LocationService


def get_optional_location_service() -> LocationService | None:
    """Return the configured geocoder-backed location service, or None.

    Use this where geocoding is optional and the caller can handle None
    gracefully (e.g. search bounding-box filter raises its own error).
    """
    try:
        return LocationService(build_geocoder(settings.geocoder_provider))
    except GeocoderConfigurationError:
        return None


def get_required_location_service() -> LocationService:
    """Return the configured geocoder-backed location service, or raise 503.

    Use this for map endpoints that cannot function without geocoding.
    """
    service = get_optional_location_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Map APIs require a configured geocoding provider.",
        )
    return service
