"""Domain models for the Search & Filter API.

A single validated :class:`SearchQuery` is the contract between the HTTP
layer, the search service and (later) a PostgreSQL-backed repository. All
filters share the existing Phase 1-9 enums and types: need categories,
priority levels, verification statuses, report statuses and location status
are never re-declared here.

Uncertainty rules:
- ``priority`` filters never match reports whose priority is unknown (they
  are excluded, never treated as LOW).
- Bounding-box filters only match reports whose raw location geocodes with
  CONFIRMED status; UNCERTAIN/missing locations are never treated as exact
  coordinates.
- Naive datetime filters are interpreted as UTC (the API's convention) so
  they compare fairly with the aware datetimes the API stores.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.ai.schemas import NeedCategory
from app.location.schemas import LocationStatus
from app.models.report import ReportStatus
from app.priority.schemas import PriorityLevel
from app.utils.validators import validate_bbox, validate_time_range
from app.verification.schemas import VerificationStatus

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class SearchSortField(str, Enum):
    """Allowed sort fields (explicit allowlist; no arbitrary attributes)."""

    TIMESTAMP = "timestamp"
    PRIORITY = "priority"
    AFFECTED_POPULATION = "affected_population"


class SearchSortOrder(str, Enum):
    """Allowed sort directions."""

    ASC = "asc"
    DESC = "desc"


class SearchQuery(BaseModel):
    """Validated filters, sorting and pagination for report search.

    Every filter is optional. When multiple filters are supplied they are ALL
    applied together (AND). The ``need`` parameter may be repeated (e.g.
    ``?need=WATER&need=FOOD``) and matches a report that has *any* of the
    requested needs. ``page_size`` is capped to keep later database-backed
    queries bounded.
    """

    q: str | None = Field(
        default=None,
        description=(
            "Case-insensitive substring search against the original report "
            "text (the preserved source evidence)."
        ),
    )
    need: list[NeedCategory] | None = Field(
        default=None,
        description=(
            "Only reports carrying at least one of these need categories. "
            "Repeat the parameter to combine needs."
        ),
    )
    priority: PriorityLevel | None = Field(
        default=None,
        description="Only reports whose backend-computed priority is this level.",
    )
    min_priority_score: float | None = Field(
        default=None, ge=0.0, le=100.0,
        description="Only reports with priority final_score >= this value.",
    )
    max_priority_score: float | None = Field(
        default=None, ge=0.0, le=100.0,
        description="Only reports with priority final_score <= this value.",
    )
    verification_status: VerificationStatus | None = Field(
        default=None,
        description="Only reports with this verification status.",
    )
    status: ReportStatus | None = Field(
        default=None,
        description="Only reports with this lifecycle status.",
    )
    location: str | None = Field(
        default=None,
        description=(
            "Case-insensitive substring match on the raw location text. "
            "Never matched by guessed coordinates."
        ),
    )
    location_status: LocationStatus | None = Field(
        default=None,
        description="Only reports with this geocoding confidence status.",
    )
    min_lat: float | None = Field(
        default=None, ge=-90.0, le=90.0,
        description="Bounding-box southern latitude (-90..90).",
    )
    max_lat: float | None = Field(
        default=None, ge=-90.0, le=90.0,
        description="Bounding-box northern latitude (-90..90).",
    )
    min_lon: float | None = Field(
        default=None, ge=-180.0, le=180.0,
        description="Bounding-box western longitude (-180..180).",
    )
    max_lon: float | None = Field(
        default=None, ge=-180.0, le=180.0,
        description="Bounding-box eastern longitude (-180..180).",
    )
    start_time: datetime | None = Field(
        default=None,
        description=(
            "Inclusive lower bound on report timestamp (ISO 8601). Naive "
            "datetimes are interpreted as UTC."
        ),
    )
    end_time: datetime | None = Field(
        default=None,
        description=(
            "Inclusive upper bound on report timestamp (ISO 8601). Naive "
            "datetimes are interpreted as UTC."
        ),
    )
    incident: str | None = Field(
        default=None,
        description="Case-insensitive substring match on the incident field.",
    )
    source: str | None = Field(
        default=None,
        description="Case-insensitive substring match on the source field.",
    )
    sort_by: SearchSortField = Field(
        default=SearchSortField.TIMESTAMP,
        description="Sort field (allowlist). Reports with an unknown value "
        "for the sort field sort last, never as a fake value.",
    )
    sort_order: SearchSortOrder = Field(
        default=SearchSortOrder.DESC,
        description="Sort direction: asc or desc.",
    )
    page: int = Field(
        default=DEFAULT_PAGE, ge=1,
        description="1-based page number.",
    )
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description="Number of items per page (1-100).",
    )

    @property
    def has_bounding_box(self) -> bool:
        """True when a complete bounding box was supplied."""
        return None not in (self.min_lat, self.max_lat, self.min_lon, self.max_lon)

    @model_validator(mode="after")
    def _validate_cross_field_ranges(self) -> "SearchQuery":
        validate_time_range(self.start_time, self.end_time)
        if (
            self.min_priority_score is not None
            and self.max_priority_score is not None
            and self.min_priority_score > self.max_priority_score
        ):
            raise ValueError("min_priority_score must be <= max_priority_score")
        validate_bbox(
            self.min_lat,
            self.max_lat,
            self.min_lon,
            self.max_lon,
            missing_message=(
                "min_lat, max_lat, min_lon and max_lon must all be supplied "
                "together to define a bounding box"
            ),
        )
        return self