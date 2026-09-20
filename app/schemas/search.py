"""Request/response schemas for the Search & Filter API.

The result item deliberately mirrors the existing Phase 1-9 types and enums
(rather than re-declaring them) and omits reporter/evidence for privacy while
keeping full traceability to the source report.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.ai.schemas import NeedCategory
from app.location.schemas import LocationStatus
from app.models.report import ReportStatus
from app.priority.schemas import PriorityLevel
from app.verification.schemas import VerificationStatus


class SearchResultItem(BaseModel):
    """One report in a search result set.

    Traceability: every item carries the source report id, preserved original
    text, timestamp, source, raw location and confidence status so a finding
    can always be traced back to its origin. Uncertainty is preserved:
    ``priority_level``/``priority_score`` are None for reports whose priority
    is unknown (never coerced to LOW), and ``location_status`` keeps the
    geocoding confidence explicit.
    """

    report_id: str
    original_text: str
    timestamp: datetime
    source: str | None = None
    location: str | None = None
    location_status: LocationStatus | None = None
    incident: str | None = None
    needs: list[NeedCategory] = Field(default_factory=list)
    status: ReportStatus
    verification_status: VerificationStatus
    priority_level: PriorityLevel | None = Field(
        default=None,
        description=(
            "Backend-computed priority level. None means the report carries "
            "no usable priority information (unknown, not LOW)."
        ),
    )
    priority_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Backend-computed priority final score. None when unknown.",
    )
    affected_population: int | None = Field(default=None, ge=0)


class SearchResponse(BaseModel):
    """Paged search results.

    ``total`` reflects the number of matching reports before pagination. An
    empty ``items`` list means there are simply no matching reports; it never
    implies zero humanitarian need (information-gap analysis is a later
    phase).
    """

    items: list[SearchResultItem] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)