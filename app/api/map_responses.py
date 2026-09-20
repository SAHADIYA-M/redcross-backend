"""Phase 12 Map projection for response activities.

GET /api/map/responses - geoprojected, privacy-safe response-activity points
                         for an interactive map (same coordinate rules and
                         geocoder as the Phase 11 report map).

Layers: HTTP -> map-responses router -> ResponseMapQuery -> ResponseMapService ->
ResponseRepository + LocationService (in-memory today, PostgreSQL later).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user
from app.api.responses import get_response_repository
from app.core.config import settings
from app.location.errors import GeocoderConfigurationError
from app.location.providers import build_geocoder
from app.location.service import LocationService
from app.map.schemas import ResponseMapQuery, ResponseMapResponse
from app.models.user import User
from app.services.response_map_service import ResponseMapService

router = APIRouter(prefix="/api/map", tags=["map-responses"])


def _required_location_service() -> LocationService:
    """Return the configured geocoder-backed location service or raise 503."""
    try:
        return LocationService(build_geocoder(settings.geocoder_provider))
    except GeocoderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Map APIs require a configured geocoding provider.",
        ) from exc


def get_response_map_service() -> ResponseMapService:
    """Build the response map service over the shared repositories."""
    return ResponseMapService(
        repository=get_response_repository(),
        location_service=_required_location_service(),
    )


@router.get("/responses", response_model=ResponseMapResponse)
def map_responses(
    params: Annotated[ResponseMapQuery, Query()],
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[ResponseMapService, Depends(get_response_map_service)],
) -> ResponseMapResponse:
    """Return geoprojected response-activity points (authenticated users only).

    Only activities whose location resolves to a CONFIRMED, in-range, non-zero
    coordinate are included. No notes or affected-population details are
    exposed; every point keeps traceability via response_id/report_id. An empty
    result never implies no response activity exists.
    """
    return service.map_responses(params)