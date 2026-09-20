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

from datetime import datetime, timezone

from app.location.schemas import LocationStatus
from app.location.service import LocationService
from app.map.schemas import (
    ResponseMapItem,
    ResponseMapQuery,
    ResponseMapResponse,
)
from app.repositories.response_repository import ResponseRepository
from app.response_activity.schemas import ResponseActivity
from app.services.map_service import is_null_island


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
        activities = [
            a for a in self._repository.get_all() if self._matches(a, query)
        ]
        items = [self._project(a) for a in activities]
        items = [item for item in items if item is not None]
        items.sort(
            key=lambda item: (_as_utc(item.timestamp), item.response_id),
            reverse=True,
        )
        return ResponseMapResponse(items=items, total=len(items))

    @staticmethod
    def _matches(activity: ResponseActivity, query: ResponseMapQuery) -> bool:
        if query.report_id is not None and activity.report_id != query.report_id:
            return False
        if query.need is not None and activity.need != query.need:
            return False
        if (
            query.response_status is not None
            and activity.response_status != query.response_status
        ):
            return False
        if query.source is not None and not _contains_ci(
            activity.source, query.source
        ):
            return False
        if query.start_time is not None and _as_utc(
            activity.timestamp
        ) < _as_utc(query.start_time):
            return False
        if query.end_time is not None and _as_utc(
            activity.timestamp
        ) > _as_utc(query.end_time):
            return False
        return True

    def _project(self, activity: ResponseActivity) -> ResponseMapItem | None:
        """Build a map point for an activity, or None if it is not mappable."""
        if activity.location is None or not activity.location.strip():
            return None
        result = self._location_service.geocode(activity.location)
        if (
            result.status != LocationStatus.CONFIRMED
            or result.latitude is None
            or result.longitude is None
        ):
            return None
        if is_null_island(result.latitude, result.longitude):
            return None
        return ResponseMapItem(
            response_id=activity.response_id,
            report_id=activity.report_id,
            latitude=result.latitude,
            longitude=result.longitude,
            location_status=LocationStatus.CONFIRMED,
            location_confidence=result.confidence,
            timestamp=activity.timestamp,
            need=activity.need,
            response_status=activity.response_status,
            activity=activity.activity,
            source=activity.source,
        )


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime for comparison without shifting its meaning."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _contains_ci(haystack: str | None, needle: str) -> bool:
    if haystack is None:
        return False
    return needle.casefold() in haystack.casefold()