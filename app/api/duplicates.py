from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.api.reports import get_report_repository
from app.duplicates.service import DuplicateDetectionService
from app.models.user import User
from app.repositories.report_repository import ReportRepository
from app.schemas.duplicate import DuplicateDetectionResponse
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["duplicates"])


def get_duplicate_service() -> DuplicateDetectionService:
    """Return the duplicate-detection service.

    It reuses the reports repository so duplicate detection sees exactly the
    reports created via the reports API. Storage is swapped in
    get_report_repository without changing this router.
    """
    return DuplicateDetectionService(get_report_repository())


@router.post("/{report_id}/duplicates", response_model=DuplicateDetectionResponse)
def detect_duplicates(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[DuplicateDetectionService, Depends(get_duplicate_service)],
) -> DuplicateDetectionResponse:
    try:
        return service.detect_duplicates(report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc