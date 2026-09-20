from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import NeedCategory, SeverityLevel
from app.conflicts.schemas import InfrastructureStatus
from app.location.schemas import LocationStatus
from app.models.report import ReportStatus
from app.verification.schemas import VerificationStatus


class CreateReport(BaseModel):
    """Input schema for creating a report.

    Structured claims (severity, affected_population, needs,
    infrastructure_status, available_needs, vulnerability,
    time_sensitivity) are optional: reports that do not carry a claim leave
    the field unset, and missing claims are never treated as conflicts.
    """

    original_text: str
    reporter: str
    timestamp: datetime | None = None
    location: str | None = None
    incident: str | None = None
    evidence: list[str] = Field(default_factory=list)
    source: str | None = None
    status: ReportStatus = ReportStatus.RECEIVED
    needs: list[NeedCategory] = Field(default_factory=list)
    location_status: LocationStatus | None = None
    severity: SeverityLevel | None = None
    affected_population: int | None = Field(default=None, ge=0)
    infrastructure_status: InfrastructureStatus | None = None
    available_needs: list[NeedCategory] = Field(default_factory=list)
    vulnerability: list[str] = Field(default_factory=list)
    time_sensitivity: str | None = None


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
    needs: list[NeedCategory] | None = None
    location_status: LocationStatus | None = None
    severity: SeverityLevel | None = None
    affected_population: int | None = Field(default=None, ge=0)
    infrastructure_status: InfrastructureStatus | None = None
    available_needs: list[NeedCategory] | None = None
    vulnerability: list[str] | None = None
    time_sensitivity: str | None = None


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
    needs: list[NeedCategory] = Field(default_factory=list)
    location_status: LocationStatus | None = None
    severity: SeverityLevel | None = None
    affected_population: int | None = Field(default=None, ge=0)
    infrastructure_status: InfrastructureStatus | None = None
    available_needs: list[NeedCategory] = Field(default_factory=list)
    vulnerability: list[str] = Field(default_factory=list)
    time_sensitivity: str | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    original_extraction: dict[str, object] = Field(default_factory=dict)