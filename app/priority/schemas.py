from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class PriorityLevel(str, Enum):
    """Final priority level derived from the backend-weighted score."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PriorityResult(BaseModel):
    """Validated result of a backend-controlled priority calculation.

    Every factor score and the final score are validated to stay within
    0-100. The final score is the deterministic weighted combination defined
    in the priority service, and the level is derived *only* from that score.
    Neither the AI nor any client can set these values directly.
    """

    report_id: str
    severity_score: float = Field(ge=0, le=100)
    affected_population_score: float = Field(ge=0, le=100)
    vulnerability_score: float = Field(ge=0, le=100)
    time_sensitivity_score: float = Field(ge=0, le=100)
    evidence_verification_score: float = Field(ge=0, le=100)
    final_score: float = Field(ge=0, le=100)
    priority_level: PriorityLevel
    calculation_version: str = "1"
    calculated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    explanations: dict[str, str] = Field(default_factory=dict)
    source_values: dict[str, str | int | list[str] | None] = Field(
        default_factory=dict
    )