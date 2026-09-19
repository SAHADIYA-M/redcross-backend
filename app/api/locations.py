from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.location.errors import (
    GeocoderConfigurationError,
    GeocoderInvalidResponseError,
    GeocoderTimeoutError,
    GeocoderUnavailableError,
)
from app.location.providers import build_geocoder
from app.location.service import LocationService
from app.schemas.location import GeocodeRequest, GeocodeResponse

router = APIRouter(prefix="/api/locations", tags=["locations"])


def get_location_service() -> LocationService:
    """Build the location service backed by the configured geocoder provider."""
    try:
        return LocationService(build_geocoder(settings.geocoder_provider))
    except GeocoderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Location service is not configured (missing geocoding provider).",
        ) from exc


@router.post("/geocode", response_model=GeocodeResponse)
def geocode_location(
    data: GeocodeRequest,
    service: Annotated[LocationService, Depends(get_location_service)],
) -> GeocodeResponse:
    try:
        result = service.geocode(data.raw_location)
    except GeocoderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Location service timed out.",
        ) from exc
    except (GeocoderUnavailableError, GeocoderInvalidResponseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Location service is currently unavailable.",
        ) from exc
    return result