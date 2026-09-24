from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.ai.schemas import NeedCategory, SeverityLevel
from app.conflicts.schemas import InfrastructureStatus
from app.location.schemas import LocationStatus
from app.models.report import ReportStatus
from app.schemas.lengths import (
    MAX_EVIDENCE_ITEM_LENGTH,
    MAX_INCIDENT_LENGTH,
    MAX_LIST_ITEMS,
    MAX_LOCATION_LENGTH,
    MAX_REPORT_TEXT_LENGTH,
    MAX_REPORTER_LENGTH,
    MAX_SOURCE_LENGTH,
    MAX_TIME_SENSITIVITY_LENGTH,
    MAX_VULNERABILITY_ITEM_LENGTH,
)
from app.verification.schemas import VerificationStatus

# Text fields are bounded so a single report payload cannot exhaust memory or
# storage while the limits stay generous for real humanitarian field reports.
EvidenceItem = Annotated[str, StringConstraints(max_length=MAX_EVIDENCE_ITEM_LENGTH)]
VulnerabilityItem = Annotated[
    str, StringConstraints(max_length=MAX_VULNERABILITY_ITEM_LENGTH)
]


class CreateReport(BaseModel):
    """Input schema for creating a report.

    Structured claims (severity, affected_population, needs,
    infrastructure_status, available_needs, vulnerability,
    time_sensitivity) are optional: reports that do not carry a claim leave
    the field unset, and missing claims are never treated as conflicts.
    """

    original_text: str = Field(max_length=MAX_REPORT_TEXT_LENGTH)
    reporter: str = Field(max_length=MAX_REPORTER_LENGTH)
    timestamp: datetime | None = None
    location: str | None = Field(default=None, max_length=MAX_LOCATION_LENGTH)
    incident: str | None = Field(default=None, max_length=MAX_INCIDENT_LENGTH)
    evidence: list[EvidenceItem] = Field(
        default_factory=list, max_length=MAX_LIST_ITEMS
    )
    source: str | None = Field(default=None, max_length=MAX_SOURCE_LENGTH)
    status: ReportStatus = ReportStatus.RECEIVED
    needs: list[NeedCategory] = Field(default_factory=list)
    location_status: LocationStatus | None = None
    severity: SeverityLevel | None = None
    affected_population: int | None = Field(default=None, ge=0)
    infrastructure_status: InfrastructureStatus | None = None
    available_needs: list[NeedCategory] = Field(default_factory=list)
    vulnerability: list[VulnerabilityItem] = Field(
        default_factory=list, max_length=MAX_LIST_ITEMS
    )
    time_sensitivity: str | None = Field(
        default=None, max_length=MAX_TIME_SENSITIVITY_LENGTH
    )


class UpdateReport(BaseModel):
    """Input schema for partially updating a report.

    Every field is optional so PATCH only changes what is sent. The original
    report text is deliberately NOT updatable: it is the immutable evidence a
    report is traceable to, and changing it would silently desynchronise the
    ``original_extraction`` snapshot captured at creation. A request that
    carries ``original_text`` is rejected with a validation error.
    """

    original_text: str | None = Field(
        default=None, max_length=MAX_REPORT_TEXT_LENGTH
    )
    reporter: str | None = Field(
        default=None, max_length=MAX_REPORTER_LENGTH
    )
    timestamp: datetime | None = None
    location: str | None = Field(default=None, max_length=MAX_LOCATION_LENGTH)
    incident: str | None = Field(default=None, max_length=MAX_INCIDENT_LENGTH)
    evidence: list[EvidenceItem] | None = Field(
        default=None, max_length=MAX_LIST_ITEMS
    )
    source: str | None = Field(default=None, max_length=MAX_SOURCE_LENGTH)
    status: ReportStatus | None = None
    needs: list[NeedCategory] | None = None
    location_status: LocationStatus | None = None
    severity: SeverityLevel | None = None
    affected_population: int | None = Field(default=None, ge=0)
    infrastructure_status: InfrastructureStatus | None = None
    available_needs: list[NeedCategory] | None = None
    vulnerability: list[VulnerabilityItem] | None = Field(
        default=None, max_length=MAX_LIST_ITEMS
    )
    time_sensitivity: str | None = Field(
        default=None, max_length=MAX_TIME_SENSITIVITY_LENGTH
    )

    @model_validator(mode="after")
    def _reject_immutable_original_text(self) -> "UpdateReport":
        if "original_text" in self.model_fields_set:
            raise ValueError(
                "original_text is immutable and cannot be changed after "
                "report creation"
            )
        return self


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