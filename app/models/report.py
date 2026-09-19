from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.ai.schemas import NeedCategory, SeverityLevel
from app.conflicts.schemas import InfrastructureStatus
from app.location.schemas import LocationStatus


class ReportStatus(str, Enum):
    """Lifecycle status of a report."""

    RECEIVED = "RECEIVED"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"


class Report(BaseModel):
    """Backend representation of a humanitarian field report.

    This is a temporary, database-independent entity so the API can be
    developed before the real database is available.

    Structured fields (severity, affected_population, needs,
    infrastructure_status, available_needs) hold the AI-validated claims about
    the report. They are optional: a report that does not provide a claim
    carries None/empty, which is never treated as a conflict.
    """

    id: str
    original_text: str
    reporter: str
    timestamp: datetime
    location: str | None = None
    incident: str | None = None
    evidence: list[str] = Field(default_factory=list)
    status: ReportStatus = ReportStatus.RECEIVED
    source: str | None = None
    needs: list[NeedCategory] = Field(default_factory=list)
    location_status: LocationStatus | None = None
    severity: SeverityLevel | None = None
    affected_population: int | None = Field(default=None, ge=0)
    infrastructure_status: InfrastructureStatus | None = None
    available_needs: list[NeedCategory] = Field(default_factory=list)