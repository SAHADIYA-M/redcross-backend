from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.report import ReportStatus


class CreateReport(BaseModel):
    """Input schema for creating a report."""

    original_text: str
    reporter: str
    timestamp: datetime | None = None
    location: str | None = None
    incident: str | None = None
    evidence: list[str] = Field(default_factory=list)
    source: str | None = None
    status: ReportStatus = ReportStatus.RECEIVED


class UpdateReport(BaseModel):
    """Input schema for partially updating a report.

    Every field is optional so PATCH only changes what is sent.
    """

    original_text: str | None = None
    reporter: str | None = None
    timestamp: datetime | None = None
    location: str | None = None
    incident: str | None = None
    evidence: list[str] | None = None
    source: str | None = None
    status: ReportStatus | None = None


class ReportResponse(BaseModel):
    """Output schema returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    original_text: str
    reporter: str
    timestamp: datetime
    location: str | None = None
    incident: str | None = None
    evidence: list[str] = Field(default_factory=list)
    status: ReportStatus = ReportStatus.RECEIVED
    source: str | None = None