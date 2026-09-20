from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.core.container import get_conflict_service
from app.models.user import User
from app.schemas.conflict import ConflictDetectionResponse
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["conflicts"])


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