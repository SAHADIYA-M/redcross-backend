"""Phase 11 Map API router.

GET /api/map/reports           - geoprojected, privacy-safe report points for
                                 an interactive map (shared Phase 10 filters).
GET /api/map/information-gaps  - per-grid-cell information sufficiency, so the
                                 frontend can show where reporting coverage is
                                 missing (never "low need").

Layers: HTTP -> router -> validated query schema -> MapService /
InformationGapService -> shared SearchService + LocationService ->
ReportRepository (in-memory today, PostgreSQL later).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user
from app.api.priority import get_priority_service
from app.api.reports import get_report_repository
from app.core.config import settings
from app.information_gap.schemas import (
    InformationGapQuery,
    InformationGapResponse,
)
from app.location.errors import GeocoderConfigurationError
from app.location.providers import build_geocoder
from app.location.service import LocationService
from app.map.schemas import MapQuery, MapResponse
from app.models.user import User
from app.search.service import LocationSearchUnavailableError, SearchService
from app.services.information_gap_service import InformationGapService
from app.services.map_service import MapService

router = APIRouter(prefix="/api/map", tags=["map"])


def get_location_service() -> LocationService | None:
    """Return the configured geocoder-backed location service.

    Returns None when the provider is not configured. The map APIs need
    geocoding to project reports, so they fail with 503 when it is missing.
    """
    try:
        return LocationService(build_geocoder(settings.geocoder_provider))
    except GeocoderConfigurationError:
        return None


def _required_location_service() -> LocationService:
    location_service = get_location_service()
    if location_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Map APIs require a configured geocoding provider.",
        )
    return location_service


def get_map_service() -> MapService:
    """Build the map service over the shared reports repository.

    Filtering reuses the Phase 10 search service (same priority + location
    services), so map and search stay consistent.
    """
    location_service = _required_location_service()
    return MapService(
        search_service=SearchService(
            repository=get_report_repository(),
            priority_service=get_priority_service(),
            location_service=location_service,
        ),
        location_service=location_service,
    )


def get_information_gap_service() -> InformationGapService:
    """Build the information-gap service over the shared reports repository."""
    location_service = _required_location_service()
    return InformationGapService(
        repository=get_report_repository(),
        location_service=location_service,
    )


@router.get("/reports", response_model=MapResponse)
def map_reports(
    params: Annotated[MapQuery, Query()],
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[MapService, Depends(get_map_service)],
) -> MapResponse:
    """Return geoprojected report points for the frontend map (auth required).

    Only reports whose location resolves to a CONFIRMED, in-range, non-zero
    coordinate are included. A report with an UNCERTAIN location keeps its
    UNCERTAIN status on the map; a report without coordinates is never placed
    at an arbitrary point. No reporter identity, raw text or evidence is
    exposed.
    """
    try:
        return service.map_reports(params)
    except LocationSearchUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/information-gaps", response_model=InformationGapResponse)
def information_gaps(
    params: Annotated[InformationGapQuery, Query()],
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[InformationGapService, Depends(get_information_gap_service)],
) -> InformationGapResponse:
    """Return per-area information-sufficiency assessments (auth required).

    An area flagged INSUFFICIENT_INFORMATION means "we do not know enough
    about this area" - it says nothing about whether need is present or
    absent. Supply a bounding box (with all four bounds) to enumerate empty
    cells explicitly; otherwise only cells holding at least one geocodable
    report are returned.
    """
    try:
        return service.analyze(params)
    except LocationSearchUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc