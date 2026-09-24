from pydantic import BaseModel, Field

from app.conflicts.schemas import PotentialConflict


class ConflictDetectionResponse(BaseModel):
    """Response schema for conflict detection.

    Reuses the domain PotentialConflict model so the relation and conflicting
    claims always agree with the conflict-detection domain rules.
    """

    report_id: str
    potential_conflicts: list[PotentialConflict] = Field(default_factory=list)