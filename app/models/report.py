from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.ai.schemas import NeedCategory
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