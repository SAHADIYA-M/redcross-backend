from enum import Enum

from pydantic import BaseModel, Field


class MatchingFactor(str, Enum):
    """Signals considered when comparing two reports."""

    LOCATION = "LOCATION"
    TIME = "TIME"
    INCIDENT = "INCIDENT"
    NEED = "NEED"
    TEXT = "TEXT"


class DuplicateRelation(str, Enum):
    """Relation attributed to a report pair.

    Detection only ever reports POTENTIAL_DUPLICATE. Deciding whether reports
    actually refer to the same incident is left to a later human review phase.
    """

    POTENTIAL_DUPLICATE = "POTENTIAL_DUPLICATE"


class PotentialDuplicate(BaseModel):
    """A possible duplicate relationship between two reports.

    This is evidence, never a verdict: reports are never deleted, merged or
    overwritten as a result of duplicate detection.
    """

    related_report_id: str
    relation: DuplicateRelation = DuplicateRelation.POTENTIAL_DUPLICATE
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    matching_factors: list[MatchingFactor] = Field(default_factory=list)