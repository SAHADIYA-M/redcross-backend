from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.reports import get_report_repository
from app.repositories.report_repository import ReportRepository
from app.schemas.priority import PriorityResponse
from app.services.priority_service import (
    InsufficientPriorityDataError,
    PriorityService,
)
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["priority"])


def get_priority_service() -> PriorityService:
    """Return the priority service over the shared reports repository.

    The calculation is fully backend-controlled: the AI never contributes a
    score. Storage is swapped in get_report_repository without touching this
    router or the calculation logic.
    """
    return PriorityService(get_report_repository())


@router.post("/{report_id}/priority", response_model=PriorityResponse)
def calculate_priority(
    report_id: str,
    service: Annotated[PriorityService, Depends(get_priority_service)],
) -> PriorityResponse:
    try:
        return service.calculate_for_report(report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InsufficientPriorityDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc