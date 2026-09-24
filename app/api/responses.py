"""Phase 12 Response Activities API router.

POST /api/responses                 - record a response activity against a
                                      validated report.
GET  /api/responses                 - list/filter response activities.
GET  /api/responses/{response_id}   - retrieve one activity.
PATCH /api/responses/{response_id}  - update an activity in place (status
                                      changes are audited).

Layers: HTTP -> router -> validated schema -> ResponseService ->
ResponseRepository + ReportRepository + AuditRepository (in-memory today,
PostgreSQL later).
"""

from app.services.response_service import ResponseService
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.container import get_response_repository, get_response_service
from app.response_activity.schemas import (
    CreateResponse,
    ResponseActivity,
    ResponseQuery,
    UpdateResponse,
)
from app.services.report_service import ReportNotFoundError
from app.services.response_service import (
    NoResponseChangeError,
    ResponseNotFoundError,
)

router = APIRouter(prefix="/api/responses", tags=["responses"])


@router.post(
    "",
    response_model=ResponseActivity,
    status_code=status.HTTP_201_CREATED,
)
def create_response(
    data: CreateResponse,
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> ResponseActivity:
    """Record a response activity against a validated report.

    The referenced report must exist (404 otherwise). RECORDING IS NOT PROOF:
    this only records that an activity was logged, it does not claim anything
    about the real world.
    """
    try:
        return service.create(data)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[ResponseActivity])
def list_responses(
    params: Annotated[ResponseQuery, Query()],
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> list[ResponseActivity]:
    """List response activities, newest first, with optional filters.

    Filters are combined with AND: report_id, need, response_status, source,
    location, start_time, end_time. Results are bounded by ``limit``
    (1-1000, default 100) with ``offset`` paging, mirroring the search
    endpoint's pagination. An empty list means no recorded activity matches;
    it never means no response exists.
    """
    return service.list(params)[params.offset : params.offset + params.limit]


@router.get("/{response_id}", response_model=ResponseActivity)
def get_response(
    response_id: str,
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> ResponseActivity:
    """Retrieve a single response activity."""
    try:
        return service.get_by_id(response_id)
    except ResponseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch("/{response_id}", response_model=ResponseActivity)
def update_response(
    response_id: str,
    data: UpdateResponse,
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> ResponseActivity:
    """Update a response activity's status or benign details in place.

    Identity (response_id/report_id/need) is preserved. A status change is
    appended to the Phase 9 audit log (action UPDATE_RESPONSE) with the
    supplied actor and reason (when provided) so the lifecycle change stays
    traceable.
    """
    try:
        return service.update(response_id, data)
    except ResponseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except NoResponseChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc