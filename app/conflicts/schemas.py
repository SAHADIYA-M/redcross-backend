from enum import Enum

from pydantic import BaseModel, Field


class InfrastructureStatus(str, Enum):
    """Operational status of infrastructure or essential services.

    Structured status is optional: a report that does not mention the status
    of infrastructure carries None, which is never treated as a conflict.
    """

    OPERATIONAL = "OPERATIONAL"
    DISRUPTED = "DISRUPTED"
    DAMAGED = "DAMAGED"
    DESTROYED = "DESTROYED"
    UNAVAILABLE = "UNAVAILABLE"


class ConflictRelation(str, Enum):
    """Relation attributed to reports holding contradictory claims.

    Detection only ever reports POTENTIAL_CONFLICT. Whether one report is
    right and the other wrong is a human decision, never the backend's.
    """

    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"


class ConflictingClaim(BaseModel):
    """A single contradictory claim shared by two reports.

    Contains the exact values from both reports and a reason so a human
    reviewer can understand why the pair was flagged.
    """

    field: str
    report_a_value: str | int | None = None
    report_b_value: str | int | None = None
    reason: str


class PotentialConflict(BaseModel):
    """A potential conflict relationship between two reports.

    Created purely for later human review: the reports themselves are never
    modified, deleted or merged, and neither side is declared truthful.
    """

    related_report_id: str
    relation: ConflictRelation = ConflictRelation.POTENTIAL_CONFLICT
    conflicts: list[ConflictingClaim] = Field(default_factory=list)