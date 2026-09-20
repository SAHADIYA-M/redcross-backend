from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user, require_roles
from app.core.container import (
    get_audit_repository,
    get_verification_service,
)
from app.models.user import REVIEWER_ROLES, User
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

_reviewer = require_roles(*sorted(REVIEWER_ROLES))


@router.patch("/{report_id}/verify", response_model=VerifyResponse)
def verify_report(
    report_id: str,
    data: VerifyRequest,
    reviewer: Annotated[User, Depends(_reviewer)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> VerifyResponse:
    """Approve, edit, reject, or mark the report's interpretation uncertain.

    Requires REVIEWER or ADMIN. The verified actor is ALWAYS the authenticated
    user: any reviewer_id supplied in the body is ignored so a client can
    never spoof who performed the action.

    Records the action in the verification history and the append-only audit
    log. After an EDIT the backend priority is recalculated from the corrected
    structured input (or invalidated when the report no longer carries usable
    priority information). Original report text and evidence are never changed
    by this endpoint.
    """
    data.reviewer_id = reviewer.user_id
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{report_id}/request-assessment",
    response_model=AssessmentRequestResponse,
)
def request_assessment(
    report_id: str,
    data: RequestAssessmentRequest,
    reviewer: Annotated[User, Depends(_reviewer)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
) -> AssessmentRequestResponse:
    """Flag a report for further human assessment.

    Requires REVIEWER or ADMIN. The recorded reviewer is ALWAYS the
    authenticated user; a body-supplied reviewer_id can never override the
    authenticated identity.

    Marks the report ASSESSMENT_REQUESTED. This is a request for further
    assessment, not a verification result — the report is not treated as
    verified.
    """
    data.reviewer_id = reviewer.user_id
    try:
        return service.request_assessment(report_id, data)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@verification_list_router.get("", response_model=list[VerificationRecord])
def list_verifications(
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[VerificationService, Depends(get_verification_service)],
    report_id: str | None = None,
    verification_status: VerificationStatus | None = None,
    action: VerificationAction | None = None,
) -> list[VerificationRecord]:
    """List verification records, newest first (authenticated users only).

    Supports optional filtering by report ID, verification status and
    verification action. Returns structured JSON suitable for a future
    responder dashboard.
    """
    return service.list_verifications(
        report_id=report_id,
        status=verification_status,
        action=action,
    )