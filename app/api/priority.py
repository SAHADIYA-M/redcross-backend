from app.services.priority_service import PriorityService
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_roles
from app.core.container import get_priority_service
from app.models.user import User, UserRole
from app.schemas.priority import PriorityResponse
from app.services.priority_service import InsufficientPriorityDataError
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["priority"])

# Requesting a priority calculation triggers backend scoring (and persists the
# result); it is an assessment request, not a read. VIEWER and RESPONDER cannot
# trigger it.
_priority_requester = require_roles(
    UserRole.ADMIN, UserRole.ASSESSOR, UserRole.REVIEWER
)


@router.post("/{report_id}/priority", response_model=PriorityResponse)
def calculate_priority(
    report_id: str,
    current_user: Annotated[User, Depends(_priority_requester)],
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc