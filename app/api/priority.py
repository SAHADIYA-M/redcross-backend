from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.core.container import get_priority_service
from app.models.user import User
from app.schemas.priority import PriorityResponse
from app.services.priority_service import InsufficientPriorityDataError
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["priority"])


@router.post("/{report_id}/priority", response_model=PriorityResponse)
def calculate_priority(
    report_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
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