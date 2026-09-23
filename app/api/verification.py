from app.verification.service import VerificationService
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.container import (
    get_audit_repository,
    get_verification_service,
)
from app.schemas.lengths import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from app.schemas.verification import (
    AssessmentRequestResponse,
    RequestAssessmentRequest,
    VerifyRequest,
    VerifyResponse,
)
from app.services.report_service import ReportNotFoundError
from app.verification.schemas import (
    VerificationAction,
    VerificationRecord,
    VerificationStatus,
)
from app.verification.service import (
    InvalidVerificationTransitionError,
    NoVerificationChangeError,
    VerificationService,
)

router = APIRouter(prefix="/api/reports", tags=["verification"])

verification_list_router = APIRouter(
    prefix="/api/verification",
    tags=["verification"],
)


@router.patch("/{report_id}/verify", response_model=VerifyResponse)
def verify_report(
    report_id: str,
    data: VerifyRequest,
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> VerifyResponse:
    """Approve, edit, reject, or mark the report's interpretation uncertain.

    Records the action in the verification history and the append-only audit
    log. After an EDIT the backend priority is recalculated from the corrected
    structured input (or invalidated when the report no longer carries usable
    priority information). Original report text and evidence are never changed
    by this endpoint.
    """
    try:
        return service.verify(report_id, data)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidVerificationTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except NoVerificationChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{report_id}/request-assessment",
    response_model=AssessmentRequestResponse,
)
def request_assessment(
    report_id: str,
    data: RequestAssessmentRequest,
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> AssessmentRequestResponse:
    """Flag a report for further human assessment.

    Marks the report ASSESSMENT_REQUESTED. This is a request for further
    assessment, not a verification result — the report is not treated as
    verified.
    """
    try:
        return service.request_assessment(report_id, data)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@verification_list_router.get("", response_model=list[VerificationRecord])
def list_verifications(
    service: Annotated[VerificationService, Depends(get_verification_service)],
    report_id: str | None = None,
    verification_status: VerificationStatus | None = None,
    action: VerificationAction | None = None,
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> list[VerificationRecord]:
    """List verification records, newest first.

    Supports optional filtering by report ID, verification status and
    verification action. Results are bounded by ``limit`` (1-1000, default
    100) with ``offset`` paging. Returns structured JSON suitable for a
    responder dashboard.
    """
    return service.list_verifications(
        report_id=report_id,
        status=verification_status,
        action=action,
    )[offset : offset + limit]