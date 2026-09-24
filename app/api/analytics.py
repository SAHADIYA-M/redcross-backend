"""Phase 12 Response Coverage API router.

GET /api/analytics/response-coverage - per-(report, need) coverage of recorded
                                       response activities.

Layers: HTTP -> analytics router -> validated CoverageQuery ->
ResponseCoverageService -> ReportRepository + ResponseRepository +
PriorityService (Phase 8) (in-memory today, PostgreSQL later).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.container import (
    get_priority_service,
    get_report_repository,
    get_response_repository,
)
from app.response_activity.schemas import (
    CoverageQuery,
    CoverageResponse,
    coverage_semantics_doc,
)
from app.services.response_coverage_service import ResponseCoverageService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_response_coverage_service() -> ResponseCoverageService:
    """Build the coverage service over the shared repositories.

    Reports, responses and the Phase 8 priority service are the exact instances
    used by their own APIs, so coverage always reflects the same data a
    responder sees elsewhere.
    """
    return ResponseCoverageService(
        report_repository=get_report_repository(),
        response_repository=get_response_repository(),
        priority_service=get_priority_service(),
    )


@router.get(
    "/response-coverage",
    response_model=CoverageResponse,
    description=coverage_semantics_doc(),
)
def response_coverage(
    params: Annotated[CoverageQuery, Query()],
    service: Annotated[
        ResponseCoverageService,
        Depends(get_response_coverage_service),
    ],
) -> CoverageResponse:
    """Compare reported needs against recorded response activities.

    Returns one row per REPORTED need of the matching reports. Priority and
    verification status of the reported need are preserved for context and are
    never fused with coverage. An empty items list means no reported need
    matches the filters; it never implies zero humanitarian need (see the
    Phase 11 information-gap endpoint for information sufficiency).
    """
    return service.calculate(params)