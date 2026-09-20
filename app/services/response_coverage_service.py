"""Phase 12 response-coverage calculation.

Layers: HTTP -> analytics router -> validated CoverageQuery ->
ResponseCoverageService -> ReportRepository + ResponseRepository +
PriorityService (Phase 8) (all in-memory today, PostgreSQL later).

PURPOSE
The service compares REPORTED NEEDS against RECORDED response activities and
answers, for each reported need of each report: is a response activity recorded
in this system? It NEVER answers "is someone responding?" or "does a response
exist?" — recording is not proof.

MATCHING (deterministic, strongest identifier first)
    response.report_id -> report -> reported needs
A response contributes to a need's coverage only when BOTH:
    response.report_id == report.id
    response.need == need
Coverage rows are emitted per reported need (report.needs). A response with
need=None is a general response to the report and is never counted as coverage
for a specific need: the system does not guess which need it served. A response
is never attached to an arbitrary report.

STATUS RULES
- Any non-CANCELLED matching response (PLANNED, IN_PROGRESS, COMPLETED) means
  RESPONSE_RECORDED (the activity genuinely is recorded; its status stays
  visible in active_response_statuses).
- CANCELLED responses are preserved for traceability but never counted: a need
  with only cancelled activities reports NO_RESPONSE_RECORDED.
- NO_RESPONSE_RECORDED means exactly "no response activity recorded". It is NOT
  "nobody is responding" and NOT "no response exists".
- UNKNOWN is defined for future unlinked response data; with report_id-required
  matching it cannot currently occur and is never produced by guessing.

QUANTITATIVE COVERAGE
coverage_percentage = reached / reported population, computed ONLY when both
sides are actually available (report.affected_population > 0 AND at least one
matching response carries affected_population). Overlapping populations across
activities are not modelled (no deduplication), so the reached figure is the
sum and is clamped at 100. Otherwise coverage stays categorical
(coverage_percentage=None) — the service never pretends to know a percentage.

SEPARATION OF CONCEPTS
Response coverage is deliberately independent of:
- the Phase 8 priority score (urgency of the reported need): priority is
  EXPOSED for context but never combined into coverage;
- the Phase 11 information-gap score (how much we trust our knowledge of an
  area): coverage items carry no gap fields and gap areas carry no response
  fields.

A REPORT WITH NO CLASSIFIED NEEDS produces no coverage row, and an empty
coverage response never implies there is no humanitarian need — an area with
zero reported needs means "insufficient information", not "nothing needed".
"""

from app.models.report import Report
from app.priority.schemas import PriorityLevel
from app.repositories.report_repository import ReportRepository
from app.repositories.response_repository import ResponseRepository
from app.response_activity.schemas import (
    CoverageItem,
    CoverageQuery,
    CoverageResponse,
    CoverageStatus,
    ResponseStatus,
)
from app.services.priority_service import (
    InsufficientPriorityDataError,
    PriorityService,
)


class ResponseCoverageService:
    """Calculates per-(report, need) response coverage from recorded data."""

    def __init__(
        self,
        report_repository: ReportRepository,
        response_repository: ResponseRepository,
        priority_service: PriorityService | None = None,
    ) -> None:
        self._report_repository = report_repository
        self._response_repository = response_repository
        self._priority_service = priority_service or PriorityService(
            report_repository
        )

    def calculate(self, query: CoverageQuery) -> CoverageResponse:
        """Return one coverage row per reported need of every matching report."""
        reports = self._report_repository.get_all()
        responses_by_report: dict[str, list] = {}
        for response in self._response_repository.get_all():
            responses_by_report.setdefault(response.report_id, []).append(
                response
            )

        items: list[CoverageItem] = []
        for report in sorted(reports, key=lambda r: r.id):
            if not self._report_matches(report, query):
                continue
            items.extend(self._report_items(report, query, responses_by_report))

        items.sort(key=lambda item: (item.report_id, item.need.value))
        return CoverageResponse(items=items, total=len(items))

    # ------------------------------------------------------------- internals

    def _report_matches(self, report: Report, query: CoverageQuery) -> bool:
        if query.report_id is not None and report.id != query.report_id:
            return False
        if query.verification_status is not None and (
            report.verification_status != query.verification_status
        ):
            return False
        if query.need is not None and query.need not in report.needs:
            return False
        if query.priority is not None:
            priority = self._priority_for(report.id)
            if priority is None or priority.priority_level != query.priority:
                # A report whose priority is unknown never matches a priority
                # filter (it is never coerced to a level), matching search.
                return False
        return True

    def _report_items(
        self,
        report: Report,
        query: CoverageQuery,
        responses_by_report: dict[str, list],
    ) -> list[CoverageItem]:
        if not report.needs:
            return []
        priority = self._priority_for(report.id)
        responses = responses_by_report.get(report.id, [])
        return [
            self._need_item(report, need, priority.priority_level if priority else None,
                            priority.final_score if priority else None, responses)
            for need in report.needs
            if query.need is None or need == query.need
        ]

    def _need_item(
        self,
        report: Report,
        need,
        priority_level: PriorityLevel | None,
        priority_score: float | None,
        responses: list,
    ) -> CoverageItem:
        matching = [
            r for r in responses
            if r.need == need and r.response_status != ResponseStatus.CANCELLED
        ]
        response_count = len(matching)
        active_statuses = sorted(
            {r.response_status for r in matching},
            key=lambda s: s.value,
        )
        latest = max(
            (r.timestamp for r in matching), default=None
        ) if matching else None

        coverage_status, percentage = self._derive_coverage(
            report=report, matching=matching, response_count=response_count
        )
        return CoverageItem(
            report_id=report.id,
            need=need,
            priority_level=priority_level,
            priority_score=priority_score,
            verification_status=report.verification_status,
            location=report.location,
            location_status=report.location_status,
            response_status=coverage_status,
            response_count=response_count,
            coverage_percentage=percentage,
            latest_response_at=latest,
            active_response_statuses=list(active_statuses),
        )

    @staticmethod
    def _derive_coverage(
        *,
        report: Report,
        matching: list,
        response_count: int,
    ) -> tuple[CoverageStatus, float | None]:
        """Decide the coverage status and (only when computable) percentage."""
        if response_count == 0:
            # CANCELLED-only activities never count as active coverage.
            return CoverageStatus.NO_RESPONSE_RECORDED, None

        served_values = [
            r.affected_population for r in matching
            if r.affected_population is not None
        ]
        reported = report.affected_population
        if reported is not None and reported > 0 and served_values:
            percentage = round(
                100.0 * min(sum(served_values), reported) / reported, 1
            )
            if percentage >= 100.0:
                return CoverageStatus.RESPONSE_RECORDED, percentage
            return CoverageStatus.PARTIAL_RESPONSE_RECORDED, percentage

        # Quantitative coverage is never invented when either side is missing.
        return CoverageStatus.RESPONSE_RECORDED, None

    def _priority_for(self, report_id: str):
        try:
            return self._priority_service.calculate_for_report(report_id)
        except InsufficientPriorityDataError:
            return None