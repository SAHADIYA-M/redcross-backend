from enum import Enum

from pydantic import BaseModel, Field


class NeedCategory(str, Enum):
    """Allowed humanitarian need categories."""

    WATER = "WATER"
    FOOD = "FOOD"
    SHELTER = "SHELTER"
    HEALTHCARE = "HEALTHCARE"
    SANITATION = "SANITATION"
    PROTECTION = "PROTECTION"
    ESSENTIAL_ITEMS = "ESSENTIAL_ITEMS"
    TRANSPORTATION = "TRANSPORTATION"
    COMMUNICATION = "COMMUNICATION"
    INFRASTRUCTURE_SERVICE = "INFRASTRUCTURE_SERVICE"
    OTHER = "OTHER"


class SeverityLevel(str, Enum):
    """Disaster severity extracted from the report."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AIExtraction(BaseModel):
    """Structured data extracted from a report by the AI.

    Values are null/empty when the report does not provide the information.
    The final priority is NOT decided here — it is computed in a later phase.
    """

    incident: str | None = None
    location: str | None = None
    needs: list[NeedCategory] = Field(default_factory=list)
    severity: SeverityLevel | None = None
    affected_population: int | None = None
    vulnerability: list[str] = Field(default_factory=list)
    time_sensitivity: str | None = None
    evidence: list[str] = Field(default_factory=list)