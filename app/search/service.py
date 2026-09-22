"""Search & Filter business logic.

Layers: HTTP -> search router -> validated SearchQuery -> SearchService ->
ReportRepository (in-memory today, PostgreSQL later).

The service depends only on the existing repository interface, the Phase 8
priority service (the single source of truth for priority scores) and the
Phase 5 location service (used only for bounding-box filters). No priority
scores are ever recomputed inside a route; no storage internals leak here.
When PostgreSQL lands, this file keeps working unchanged and the repository
can translate the same SearchQuery into efficient database filters.
"""

from app.location.schemas import LocationStatus
from app.location.service import LocationService
from app.models.report import Report
from app.repositories.report_repository import ReportRepository
from app.schemas.priority import PriorityResponse
from app.schemas.search import SearchResponse, SearchResultItem
from app.search.schemas import SearchQuery, SearchSortField, SearchSortOrder
from app.services.priority_service import (
    InsufficientPriorityDataError,
    PriorityService,
)
from app.utils.datetime_utils import as_utc
from app.utils.strings import contains_ci


class LocationSearchUnavailableError(Exception):
    """Raised when a bounding-box search needs a geocoder that is not set up."""

    def __init__(self) -> None:
        super().__init__(
            "Bounding-box search requires a configured location service"
        )



class SearchService:
    """Applies a SearchQuery to reports and returns a paged result set.

    Filtering currently scans the in-memory repository because this is an MVP.
    Each filter is a small, composable method so every condition maps cleanly
    onto a SQL WHERE clause when a database repository arrives.
    """

    def __init__(
        self,
        repository: ReportRepository,
        priority_service: PriorityService | None = None,
        location_service: LocationService | None = None,
    ) -> None:
        self._repository = repository
        self._priority_service = priority_service or PriorityService(repository)
        self._location_service = location_service

    def search(self, query: SearchQuery) -> SearchResponse:
        """Run the query and return a paged, sorted result set.

        Priority is computed once per report (and only for reports that can
        carry a priority) through the Phase 8 service, then reused for
        filtering, sorting and output - a score is never calculated twice
        within a single request. Reports without usable priority input carry
        None/None and are handled as "unknown" everywhere - they are excluded
        only when a priority filter explicitly requires a value, and they sort
        last rather than as LOW.
        """
        candidates, priorities = self.filtered_reports_with_priorities(query)
        ordered = self._sort(candidates, query, priorities)

        total = len(ordered)
        start = (query.page - 1) * query.page_size
        page_items = ordered[start : start + query.page_size]
        return SearchResponse(
            items=[self._to_item(report, priorities) for report in page_items],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    def filtered_reports_with_priorities(
        self, query: SearchQuery
    ) -> tuple[list[Report], dict[str, PriorityResponse | None]]:
        """Return reports matching ``query`` plus their priorities.

        Non-priority filters are applied first, then priority scores are
        computed exactly once for the reduced candidate set and reused by the
        priority filter, sorting and output. Shared by /api/search/reports and
        the Phase 11 map endpoint so filter behaviour and priority scoring are
        implemented exactly once and never duplicated within one request.
        """
        # A bounding-box search needs a working geocoder; fail fast rather
        # than silently returning empty results when it is not configured.
        if query.has_bounding_box and self._location_service is None:
            raise LocationSearchUnavailableError()

        candidates = self._candidates_for(query)
        priorities = self._priority_map(candidates)
        if self._has_priority_filter(query):
            candidates = [
                report
                for report in candidates
                if self._matches_priority(report.id, query, priorities)
            ]
        return candidates, priorities

    def _candidates_for(self, query: SearchQuery) -> list[Report]:
        """Return the reports matching every non-priority filter of ``query``.

        Without a bounding box the repository may push the filters down into
        the database (``search_reports``). The bounding-box and all priority
        filters are computed here in Python: priorities stay with the Phase 8
        service and the geocoder stays with the Phase 5 location service.
        """
        if not query.has_bounding_box:
            try:
                pushed = self._repository.search_reports(query)
                if pushed is not None:
                    return pushed
            except NotImplementedError:
                pass
        return [
            report
            for report in self._repository.get_all()
            if self._matches(report, query)
        ]

    # ------------------------------------------------------------- filtering

    def _matches(self, report: Report, query: SearchQuery) -> bool:
        """Apply every non-priority filter; all conditions must hold (AND)."""
        if query.q is not None and not contains_ci(report.original_text, query.q):
            return False
        if query.need and not any(need in report.needs for need in query.need):
            return False
        if (
            query.verification_status is not None
            and report.verification_status != query.verification_status
        ):
            return False
        if query.status is not None and report.status != query.status:
            return False
        if query.location is not None and not contains_ci(report.location, query.location):
            return False
        if (
            query.location_status is not None
            and report.location_status != query.location_status
        ):
            return False
        if query.incident is not None and not contains_ci(report.incident, query.incident):
            return False
        if query.source is not None and not contains_ci(report.source, query.source):
            return False
        if not self._matches_time(report, query):
            return False
        if query.has_bounding_box and not self._matches_bbox(report, query):
            return False
        return True

    def _matches_time(self, report: Report, query: SearchQuery) -> bool:
        if query.start_time is None and query.end_time is None:
            return True
        timestamp = as_utc(report.timestamp)
        if query.start_time is not None and timestamp < as_utc(query.start_time):
            return False
        if query.end_time is not None and timestamp > as_utc(query.end_time):
            return False
        return True

    def _matches_bbox(self, report: Report, query: SearchQuery) -> bool:
        """Bounding-box match using only CONFIRMED geocoding results.

        UNCERTAIN or missing locations are never treated as exact coordinates
        and therefore never match a bounding box.
        """
        if report.location is None or not report.location.strip():
            return False
        result = self._location_service.geocode(report.location)
        if (
            result.status != LocationStatus.CONFIRMED
            or result.latitude is None
            or result.longitude is None
        ):
            return False
        return (
            query.min_lat <= result.latitude <= query.max_lat
            and query.min_lon <= result.longitude <= query.max_lon
        )

    def _matches_priority(
        self,
        report_id: str,
        query: SearchQuery,
        priorities: dict[str, PriorityResponse | None],
    ) -> bool:
        """Apply priority filters; reports with unknown priority never match."""
        if not self._has_priority_filter(query):
            return True
        priority = priorities.get(report_id)
        if priority is None:
            return False
        if query.priority is not None and priority.priority_level != query.priority:
            return False
        if (
            query.min_priority_score is not None
            and priority.final_score < query.min_priority_score
        ):
            return False
        if (
            query.max_priority_score is not None
            and priority.final_score > query.max_priority_score
        ):
            return False
        return True

    # ---------------------------------------------------------------- sorting

    def _sort(
        self,
        reports: list[Report],
        query: SearchQuery,
        priorities: dict[str, PriorityResponse | None],
    ) -> list[Report]:
        """Sort using the explicit allowlist and a deterministic tie-breaker.

        Reports whose value for the sort field is unknown sort last, never as
        a fabricated value (e.g. unknown priority is not treated as LOW).
        """
        descending = query.sort_order == SearchSortOrder.DESC

        if query.sort_by == SearchSortField.TIMESTAMP:
            primary = lambda r: as_utc(r.timestamp)  # noqa: E731
        elif query.sort_by == SearchSortField.PRIORITY:
            primary = lambda r: (
                priorities.get(r.id).final_score
                if priorities.get(r.id) is not None
                else None
            )  # noqa: E731
        else:  # AFFECTED_POPULATION
            primary = lambda r: r.affected_population  # noqa: E731

        known = [r for r in reports if primary(r) is not None]
        unknown = [r for r in reports if primary(r) is None]
        known.sort(key=lambda r: (primary(r), r.id), reverse=descending)
        unknown.sort(key=lambda r: r.id)
        return known + unknown

    # ----------------------------------------------------------------- output

    def _to_item(
        self,
        report: Report,
        priorities: dict[str, PriorityResponse | None],
    ) -> SearchResultItem:
        priority = priorities.get(report.id)
        return SearchResultItem(
            report_id=report.id,
            original_text=report.original_text,
            timestamp=report.timestamp,
            source=report.source,
            location=report.location,
            location_status=report.location_status,
            incident=report.incident,
            needs=list(report.needs),
            status=report.status,
            verification_status=report.verification_status,
            priority_level=priority.priority_level if priority else None,
            priority_score=priority.final_score if priority else None,
            affected_population=report.affected_population,
        )

    def _priority_map(self, reports: list[Report]) -> dict[str, PriorityResponse | None]:
        """Compute priority once per report via the Phase 8 service.

        Reports without usable priority input map to None (unknown), cached so
        filtering, sorting and output all agree within a single search call.
        """
        return {
            report.id: self._calculate(report.id)
            for report in reports
            if report.has_priority_signal
        }

    @staticmethod
    def _has_priority_filter(query: SearchQuery) -> bool:
        """True when the query needs priority values for filtering."""
        return (
            query.priority is not None
            or query.min_priority_score is not None
            or query.max_priority_score is not None
        )

    def _calculate(self, report_id: str) -> PriorityResponse | None:
        try:
            return self._priority_service.calculate_for_report(report_id)
        except InsufficientPriorityDataError:
            return None