from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.container import get_fusion_repository, get_fusion_service
from app.models.fusion import FusionType, FusionStatus
from app.repositories.fusion_repository import FusionRepository
from app.schemas.fusion import FusionCandidateResponse, ResolveFusionRequest
from app.schemas.lengths import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from app.services.fusion_service import FusionService

router = APIRouter(prefix="/api/fusion", tags=["fusion"])


@router.get("", response_model=list[FusionCandidateResponse])
def get_fusion_candidates(
    repository: Annotated[FusionRepository, Depends(get_fusion_repository)],
    status: Optional[FusionStatus] = Query(default=FusionStatus.PENDING),
    type: Optional[FusionType] = Query(default=None),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> list[FusionCandidateResponse]:
    """Return fusion candidates, one bounded page (deterministic order).

    The candidate queue can grow with the number of report pairs, so the list
    is paginated (``limit`` 1-1000, default 100, with ``offset``) like every
    other list endpoint; ordering is by ``created_at`` then id so page
    boundaries are stable across requests.
    """
    candidates = repository.get_all()
    if status:
        candidates = [c for c in candidates if c.status == status]
    if type:
        candidates = [c for c in candidates if c.type == type]
    candidates = sorted(
        candidates,
        key=lambda candidate: (candidate.created_at, candidate.id),
    )
    return candidates[offset : offset + limit]


@router.get("/{candidate_id}", response_model=FusionCandidateResponse)
def get_fusion_candidate(
    candidate_id: str,
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
    service: Annotated[FusionService, Depends(get_fusion_service)],
) -> FusionCandidateResponse:
    """Resolve a fusion candidate."""
    candidate = service.resolve(candidate_id, request.action)
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' not found",
        )
    return candidate
