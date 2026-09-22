"""Phase 11 map business logic.

Layers: HTTP -> map router -> validated MapQuery -> MapService ->
SearchService (shared Phase 10 filters) + LocationService (geoprojection) ->
ReportRepository (in-memory today, PostgreSQL later).

The map reuses Phase 10 filtering and priority scoring via
SearchService.filtered_reports_with_priorities so the time/need/priority/
verification/incident/source/bbox rules have exactly one implementation and
priority is computed once per request. This service only adds the geographic
projection:

- a report appears as a point ONLY when its location resolves to a CONFIRMED
  geocode with in-range coordinates that are NOT the 0,0 "null island"
  fallback (0,0 is never used as a fake location);
- the Phase 5 location_status is preserved (UNCERTAIN stays UNCERTAIN) and
  location_confidence is whatever the provider actually returned (null when
  it returned none - never invented);
- no reporter identity, raw text or evidence is exposed.
"""

from app.location.projection import resolve_confirmed_point
from app.location.schemas import LocationStatus
from app.location.service import LocationService
from app.map.schemas import (
    MapQuery,
    MapReportItem,
    MapResponse,
    MapSortField,
    MapSortOrder,
)
from app.models.report import Report
from app.search.service import SearchService


class MapService:
    """Projects filtered reports into privacy-safe map points."""

    def __init__(
        self,
        search_service: SearchService,
        location_service: LocationService,
    ) -> None:
        self._search_service = search_service
        self._location_service = location_service

    def map_reports(self, query: MapQuery) -> MapResponse:
        """Return the mappable reports matching ``query``.

        Filtering is delegated to the shared Phase 10 service (same rules as
        /api/search/reports, with priority computed exactly once). Every
        matching report is then geocoded for projection; only reports with
        CONFIRMED, in-range, non-zero coordinates become points.
        """
        matched, priorities = self._search_service.filtered_reports_with_priorities(
            query.to_search_query()
        )
        items = [self._project(report, priorities.get(report.id)) for report in matched]
        items = [item for item in items if item is not None]
        ordered = self._sort(items, query)
        # The response is bounded to the requested page while ``total`` keeps
        # the full mappable count, so a client can page through a large map
        # without a single request materialising every point.
        total = len(ordered)
        page = ordered[query.offset : query.offset + query.limit]
        return MapResponse(items=page, total=total)

    def _project(
        self,
        report: Report,
        priority,
    ) -> MapReportItem | None:
        """Build a map point for a report, or None if it is not mappable."""
        point = resolve_confirmed_point(report.location, self._location_service)
        if point is None:
            return None
        lat, lng, confidence = point
        return MapReportItem(
            report_id=report.id,
            latitude=lat,
            longitude=lng,
            # Preserve the Phase 5 status when the report carries one;
            # otherwise fall back to CONFIRMED (resolve_confirmed_point guarantees it).
            location_status=report.location_status or LocationStatus.CONFIRMED,
            location_confidence=confidence,
            timestamp=report.timestamp,
            incident=report.incident,
            needs=list(report.needs),
            priority_level=priority.priority_level if priority is not None else None,
            priority_score=priority.final_score if priority is not None else None,
            verification_status=report.verification_status,
            report_status=report.status,
            source=report.source,
        )

    @staticmethod
    def _sort(items: list[MapReportItem], query: MapQuery) -> list[MapReportItem]:
        """Sort by the allowlisted field with a deterministic id tie-break."""
        descending = query.sort_order == MapSortOrder.DESC

        if query.sort_by == MapSortField.TIMESTAMP:
            key = lambda item: (item.timestamp, item.report_id)  # noqa: E731
        elif query.sort_by == MapSortField.LONGITUDE:
            key = lambda item: (item.longitude, item.report_id)  # noqa: E731
        else:  # LATITUDE (default)
            key = lambda item: (item.latitude, item.report_id)  # noqa: E731

        return sorted(items, key=key, reverse=descending)


__all__ = ["MapService"]