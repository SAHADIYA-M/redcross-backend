"""Phase 12 map projection for response activities.

Layers: HTTP -> map-responses router -> ResponseMapQuery -> ResponseMapService ->
ResponseRepository + LocationService (in-memory today, PostgreSQL later).

The same geographic rules as the Phase 11 report map apply, so coordinates are
never invented:

- an activity appears as a point ONLY when its raw location resolves to a
  CONFIRMED geocode with in-range coordinates that are NOT the 0,0 "null
  island" fallback;
- UNCERTAIN/ambiguous/missing locations are never placed anywhere;
- location_confidence is whatever the provider actually returned (None when it
  returned none - never invented);
- notes and affected-population details are omitted (map hygiene); every point
  stays traceable via response_id/report_id.

An empty projection never implies no response activity exists: it only means no
recorded activity has valid coordinates here.
"""

from app.location.projection import resolve_confirmed_point
from app.location.schemas import LocationStatus
from app.location.service import LocationService
from app.map.schemas import (
    ResponseMapItem,
    ResponseMapQuery,
    ResponseMapResponse,
)
from app.repositories.response_repository import ResponseRepository
from app.response_activity.schemas import ResponseActivity, ResponseQuery
from app.services.response_service import matches_response_activity
from app.utils.datetime_utils import as_utc


class ResponseMapService:
    """Projects recorded response activities into privacy-safe map points."""

    def __init__(
        self,
        repository: ResponseRepository,
        location_service: LocationService,
    ) -> None:
        self._repository = repository
        self._location_service = location_service

    def map_responses(self, query: ResponseMapQuery) -> ResponseMapResponse:
        """Return the mappable response activities matching ``query``."""
        filter_query = ResponseQuery(
            report_id=query.report_id,
            need=query.need,
            response_status=query.response_status,
            source=query.source,
            start_time=query.start_time,
            end_time=query.end_time,
        )
        activities = [
            a
            for a in self._repository.get_all()
            if matches_response_activity(a, filter_query)
        ]
        items = [self._project(a) for a in activities]
        items = [item for item in items if item is not None]
        items.sort(
            key=lambda item: (as_utc(item.timestamp), item.response_id),
            reverse=True,
        )
        return ResponseMapResponse(items=items, total=len(items))

    def _project(self, activity: ResponseActivity) -> ResponseMapItem | None:
        """Build a map point for an activity, or None if it is not mappable."""
        point = resolve_confirmed_point(activity.location, self._location_service)
        if point is None:
            return None
        lat, lng, confidence = point
        return ResponseMapItem(
            response_id=activity.response_id,
            report_id=activity.report_id,
            latitude=lat,
            longitude=lng,
            location_status=LocationStatus.CONFIRMED,
            location_confidence=confidence,
            timestamp=activity.timestamp,
            need=activity.need,
            response_status=activity.response_status,
            activity=activity.activity,
            source=activity.source,
        )