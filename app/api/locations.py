from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.api.geocoder_deps import get_optional_location_service
from app.location.errors import (
    GeocoderInvalidResponseError,
    GeocoderTimeoutError,
    GeocoderUnavailableError,
)
from app.location.service import LocationService
from app.models.user import User
from app.schemas.location import GeocodeRequest, GeocodeResponse

router = APIRouter(prefix="/api/locations", tags=["locations"])


def get_location_service() -> LocationService:
    """Build the location service backed by the configured geocoder provider."""
    service = get_optional_location_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Location service is not configured.",
        )
    return service


@router.post("/geocode", response_model=GeocodeResponse)
def geocode_location(
    data: GeocodeRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
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