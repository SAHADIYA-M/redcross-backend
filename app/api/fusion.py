from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_active_user
from app.core.container import get_fusion_repository, get_fusion_service
from app.models.user import User
from app.models.fusion import FusionType, FusionStatus
from app.repositories.fusion_repository import FusionRepository
from app.schemas.fusion import FusionCandidateResponse, ResolveFusionRequest
from app.services.fusion_service import FusionService

router = APIRouter(prefix="/api/fusion", tags=["fusion"])


@router.get("", response_model=list[FusionCandidateResponse])
def get_fusion_candidates(
    current_user: Annotated[User, Depends(get_current_active_user)],
    repository: Annotated[FusionRepository, Depends(get_fusion_repository)],
    status: Optional[FusionStatus] = Query(default=FusionStatus.PENDING),
    type: Optional[FusionType] = Query(default=None),
) -> list[FusionCandidateResponse]:
    """Return pending fusion candidates."""
    # Assuming ANY authenticated user can view them
    candidates = repository.get_all()
    if status:
        candidates = [c for c in candidates if c.status == status]
    if type:
        candidates = [c for c in candidates if c.type == type]
    return candidates


@router.get("/{candidate_id}", response_model=FusionCandidateResponse)
def get_fusion_candidate(
    candidate_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    repository: Annotated[FusionRepository, Depends(get_fusion_repository)],
) -> FusionCandidateResponse:
    candidate = repository.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' not found",
        )
    return candidate


@router.post("/{candidate_id}/resolve", response_model=FusionCandidateResponse)
def resolve_fusion_candidate(
    candidate_id: str,
    request: ResolveFusionRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[FusionService, Depends(get_fusion_service)],
) -> FusionCandidateResponse:
    """Resolve a fusion candidate."""
    if current_user.role.value not in ["ADMIN", "REVIEWER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be a REVIEWER or ADMIN to resolve fusion candidates",
        )
    
    candidate = service.resolve(candidate_id, request.action, current_user.user_id)
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' not found",
        )
    return candidate
