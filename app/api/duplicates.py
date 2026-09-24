from app.duplicates.service import DuplicateDetectionService
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.container import get_duplicate_service
from app.schemas.duplicate import DuplicateDetectionResponse
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["duplicates"])


@router.post("/{report_id}/duplicates", response_model=DuplicateDetectionResponse)
def detect_duplicates(
    report_id: str,
    service: Annotated[DuplicateDetectionService, Depends(get_duplicate_service)],
) -> DuplicateDetectionResponse:
    try:
        return service.detect_duplicates(report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc