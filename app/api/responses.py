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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user, require_roles
from app.api.reports import get_report_repository
from app.api.verification import get_audit_repository
from app.models.user import RESPONDER_ROLES, User
from app.repositories.response_repository import ResponseRepository
from app.repositories.in_memory_response_repository import (
    InMemoryResponseRepository,
)
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
    ResponseService,
)

router = APIRouter(prefix="/api/responses", tags=["responses"])

_response_repository = InMemoryResponseRepository()

_responder = require_roles(*sorted(RESPONDER_ROLES))


def get_response_repository() -> ResponseRepository:
    """Return the shared in-memory response repository.

    A single instance is created once at import time so response activities
    persist across requests. Swap the storage backend here (e.g. for a
    database-backed repository) without touching the router.
    """
    return _response_repository


def get_response_service() -> ResponseService:
    """Build the response service over the shared repositories.

    Responses, reports and the audit log all share the same instances used by
    their own APIs, so recorded activities, validated reports and audit
    entries stay consistent.
    """
    return ResponseService(
        get_response_repository(),
        get_report_repository(),
        get_audit_repository(),
    )


@router.post(
    "",
    response_model=ResponseActivity,
    status_code=status.HTTP_201_CREATED,
)
def create_response(
    data: CreateResponse,
    responder: Annotated[User, Depends(_responder)],
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> ResponseActivity:
    """Record a response activity against a validated report.

    Requires RESPONDER or ADMIN. The referenced report must exist (404
    otherwise). RECORDING IS NOT PROOF: this only records that an activity was
    logged, it does not claim anything about the real world.
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
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> list[ResponseActivity]:
    """List response activities, newest first, with optional filters.

    Filters are combined with AND: report_id, need, response_status, source,
    location, start_time, end_time. An empty list means no recorded activity
    matches; it never means no response exists.
    """
    return service.list(params)


@router.get("/{response_id}", response_model=ResponseActivity)
def get_response(
    response_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> ResponseActivity:
    """Retrieve a single response activity (authenticated users only)."""
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
    responder: Annotated[User, Depends(_responder)],
    service: Annotated[ResponseService, Depends(get_response_service)],
) -> ResponseActivity:
    """Update a response activity's status or benign details in place.

    Requires RESPONDER or ADMIN. The authenticated identity is authoritative:
    any actor_id supplied in the body is replaced with the authenticated user
    so a client can never spoof who changed the activity.

    Identity (response_id/report_id/need) is preserved. A status change is
    appended to the Phase 9 audit log (action UPDATE_RESPONSE) with the
    authenticated actor and reason so the lifecycle change stays traceable.
    """
    data.actor_id = responder.user_id
    try:
        return service.update(response_id, data)
    except ResponseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except NoResponseChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc