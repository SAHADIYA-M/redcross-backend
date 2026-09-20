from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.api.reports import get_report_repository
from app.conflicts.service import ConflictDetectionService
from app.models.user import User
from app.repositories.report_repository import ReportRepository
from app.schemas.conflict import ConflictDetectionResponse
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["conflicts"])


def get_conflict_service() -> ConflictDetectionService:
    """Return the conflict-detection service.

    It reuses the reports repository so conflict detection sees exactly the
    reports created via the reports API. Storage is swapped in
    get_report_repository without changing this router.
    """
    return ConflictDetectionService(get_report_repository())


@router.post("/{report_id}/conflicts", response_model=ConflictDetectionResponse)
def detect_conflicts(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[
        ConflictDetectionService, Depends(get_conflict_service)
    ],
) -> ConflictDetectionResponse:
    try:
        return service.detect_conflicts(report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc