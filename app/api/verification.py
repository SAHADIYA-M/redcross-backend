from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.reports import get_report_repository
from app.repositories.audit_repository import AuditRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.repositories.verification_repository import VerificationRepository
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

_verification_repository = InMemoryVerificationRepository()
_audit_repository = InMemoryAuditRepository()


def get_verification_repository() -> VerificationRepository:
    """Return the shared in-memory verification repository.

    A single instance is created once at import time so verification records
    persist across requests. Swap the storage backend here without touching
    the routers.
    """
    return _verification_repository


def get_audit_repository() -> AuditRepository:
    """Return the shared in-memory audit repository (append-only)."""
    return _audit_repository


def get_verification_service() -> VerificationService:
    """Build the verification service over the shared repositories.

    The report repository is the same instance used by the reports API, so
    verification writes are visible everywhere. Storage backends are swapped
    here (e.g. for a database-backed repository) without changing the router.
    """
    return VerificationService(
        get_report_repository(),
        get_verification_repository(),
        get_audit_repository(),
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
) -> list[VerificationRecord]:
    """List verification records, newest first.

    Supports optional filtering by report ID, verification status and
    verification action. Returns structured JSON suitable for a future
    responder dashboard.
    """
    return service.list_verifications(
        report_id=report_id,
        status=verification_status,
        action=action,
    )