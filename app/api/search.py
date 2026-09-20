"""Search & Filter API router.

GET /api/search/reports combines any number of filters (AND), sorts the
matches by an allowlisted field, and returns one page. All parameter
validation is delegated to the SearchQuery schema so values that are invalid
(invalid enums, out-of-range coordinates, inverted date/score ranges, bad
pagination) produce consistent FastAPI 422 responses without exposing
internal exceptions.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user
from app.api.priority import get_priority_service
from app.api.reports import get_report_repository
from app.core.config import settings
from app.location.errors import GeocoderConfigurationError
from app.location.providers import build_geocoder
from app.location.service import LocationService
from app.models.user import User
from app.repositories.report_repository import ReportRepository
from app.schemas.search import SearchResponse
from app.search.schemas import SearchQuery
from app.search.service import LocationSearchUnavailableError, SearchService
from app.services.priority_service import PriorityService

router = APIRouter(prefix="/api/search", tags=["search"])


def get_location_service() -> LocationService | None:
    """Return the configured geocoder-backed location service.

    Returns None when the provider is not configured. Bounding-box filters
    need this service; all other filters work without it.
    """
    try:
        return LocationService(build_geocoder(settings.geocoder_provider))
    except GeocoderConfigurationError:
        return None


def get_search_service() -> SearchService:
    """Build the search service over the shared reports repository.

    The Phase 8 priority service and (optionally) the Phase 5 location
    service are wired here; storage remains the same shared in-memory
    repository used by the reports API.
    """
    return SearchService(
        repository=get_report_repository(),
        priority_service=get_priority_service(),
        location_service=get_location_service(),
    )


@router.get("/reports", response_model=SearchResponse)
def search_reports(
    params: Annotated[SearchQuery, Query()],
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[SearchService, Depends(get_search_service)],
) -> SearchResponse:
    """Search and filter humanitarian reports (authenticated users only).

    Combines every supplied filter (AND semantics), sorts the matches by the
    allowlisted sort field, and returns ``page_size`` results for the
    requested ``page``. An empty result means simply that no report matches;
    it never implies zero humanitarian need.
    """
    try:
        return service.search(params)
    except LocationSearchUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc