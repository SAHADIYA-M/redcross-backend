from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.ai.schemas import NeedCategory, SeverityLevel
from app.conflicts.schemas import InfrastructureStatus
from app.location.schemas import LocationStatus
from app.verification.schemas import VerificationStatus


class ReportStatus(str, Enum):
    """Lifecycle status of a report."""

    RECEIVED = "RECEIVED"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"


DEFAULT_CLUSTER_LOCATION = "Unknown Location"
DEFAULT_CLUSTER_NEED = "General Request"


class Report(BaseModel):
    """Backend representation of a humanitarian field report.

    This is a temporary, database-independent entity so the API can be
    developed before the real database is available.

    Structured fields (severity, affected_population, needs,
    infrastructure_status, available_needs, vulnerability,
    time_sensitivity) hold the AI-validated claims about the report. They are
    optional: a report that does not provide a claim carries None/empty,
    which is never treated as a conflict. The backend converts these claims
    into factor scores; neither severity nor any other claim is ever turned
    into a final priority by the AI.
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
    vulnerability: list[str] = Field(default_factory=list)
    time_sensitivity: str | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    original_extraction: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Immutable snapshot of the AI-generated structured interpretation "
            "as first persisted. Never overwritten by verification, so AI "
            "output always stays distinguishable from human corrections. "
            "Populated in ReportService.create; the verification workflow "
            "never touches it."
        ),
    )

    @property
    def has_priority_signal(self) -> bool:
        """True when any structured field could feed the backend priority.

        Single source of truth for "is this report worth attempting a priority
        calculation" — used by both the priority service (which refuses to
        calculate without a signal) and the search/filter layer (which skips
        calculation for reports that can never carry one).
        """
        return bool(
            self.severity is not None
            or self.affected_population is not None
            or self.vulnerability
            or self.time_sensitivity
            or self.evidence
        )

    @property
    def cluster_location(self) -> str:
        """Normalized location used for duplicate/conflict cluster keys."""
        return self.location or DEFAULT_CLUSTER_LOCATION

    @property
    def cluster_need(self) -> str:
        """Normalized first need used for duplicate/conflict cluster keys."""
        return self.needs[0].value if self.needs else DEFAULT_CLUSTER_NEED