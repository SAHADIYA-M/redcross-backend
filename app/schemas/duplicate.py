from pydantic import BaseModel, Field

from app.duplicates.schemas import PotentialDuplicate


class DuplicateDetectionResponse(BaseModel):
    """Response schema for duplicate detection.

    Reuses the domain PotentialDuplicate model so the relation/score/factors
    always agree with the duplicate-detection domain rules.
    """

    report_id: str
    potential_duplicates: list[PotentialDuplicate] = Field(default_factory=list)