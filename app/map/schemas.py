"""Domain models for the Phase 11 Map API.

The map endpoint returns geospatially useful, privacy-safe report points for
an interactive frontend map. All enums (need categories, priority levels,
verification/report/location statuses) are the existing Phase 1-10
definitions; nothing is re-declared here.

Filtering reuses the Phase 10 SearchQuery through :meth:`MapQuery.
to_search_query` - a map filter and its search counterpart share every
validation rule (enums, coordinate bounds, inverted/partial bounding boxes,
inverted date ranges), so there is exactly one implementation of time, need,
priority, verification, source, incident and geographic filtering.

Only reports with a valid resolved coordinate appear in the map response.
A report is mappable when its location geocodes to CONFIRMED with in-range
coordinates that are NOT the 0,0 "null island" fallback; reports without
coordinates, or marked UNCERTAIN, are never silently placed anywhere.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.ai.schemas import NeedCategory
from app.location.schemas import LocationStatus
from app.models.report import ReportStatus
from app.priority.schemas import PriorityLevel
from app.response_activity.schemas import ResponseStatus
from app.schemas.lengths import (
    DEFAULT_LIST_LIMIT,
    MAX_INCIDENT_LENGTH,
    MAX_LIST_LIMIT,
    MAX_REPORT_ID_LENGTH,
    MAX_SOURCE_LENGTH,
)
from app.search.schemas import MAX_PAGE_SIZE, SearchQuery
from app.utils.validators import validate_time_range
from app.verification.schemas import VerificationStatus


class MapSortField(str, Enum):
    """Allowed sort fields for map points (deterministic tie-break by id)."""

    LATITUDE = "latitude"
    LONGITUDE = "longitude"
    TIMESTAMP = "timestamp"


class MapSortOrder(str, Enum):
    """Allowed sort directions for map points."""

    ASC = "asc"
    DESC = "desc"


class MapQuery(BaseModel):
    """Validated filters for GET /api/map/reports.

    Everyday filters (need, priority, verification/report status, incident,
    source, time) plus an optional geographic bounding box. Every rule is
    the SearchQuery rule: when the query is converted it is re-validated by
    SearchQuery, so a partial bounding box, inverted date range or inverted
    bbox is rejected exactly as it is for search.
    """

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
    report_status: ReportStatus | None = Field(
        default=None,
        description="Only reports with this lifecycle status.",
    )
    incident: str | None = Field(
        default=None,
        max_length=MAX_INCIDENT_LENGTH,
        description="Case-insensitive substring match on the incident field.",
    )
    source: str | None = Field(
        default=None,
        max_length=MAX_SOURCE_LENGTH,
        description="Case-insensitive substring match on the source field.",
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
    sort_by: MapSortField = Field(
        default=MapSortField.LATITUDE,
        description="Sort field for the returned points (allowlist).",
    )
    sort_order: MapSortOrder = Field(
        default=MapSortOrder.DESC,
        description="Sort direction: asc or desc.",
    )
    limit: int = Field(
        default=DEFAULT_LIST_LIMIT,
        ge=1,
        le=MAX_LIST_LIMIT,
        description="Maximum number of map points to return in this page "
        "(1-1000, default 100).",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of map points to skip before this page.",
    )

    @property
    def has_bounding_box(self) -> bool:
        """True when a complete bounding box was supplied."""
        return None not in (self.min_lat, self.max_lat, self.min_lon, self.max_lon)

    def to_search_query(self) -> SearchQuery:
        """Build the equivalent Phase 10 filter, reusing its validation.

        Only the map-relevant filters are mapped; search-only options (free
        text, raw-location substring, paging, sort) are intentionally left
        at their defaults.
        """
        return SearchQuery(
            need=self.need,
            priority=self.priority,
            min_priority_score=self.min_priority_score,
            max_priority_score=self.max_priority_score,
            verification_status=self.verification_status,
            status=self.report_status,
            incident=self.incident,
            source=self.source,
            start_time=self.start_time,
            end_time=self.end_time,
            min_lat=self.min_lat,
            max_lat=self.max_lat,
            min_lon=self.min_lon,
            max_lon=self.max_lon,
            page=1,
            page_size=MAX_PAGE_SIZE,
        )

    @model_validator(mode="after")
    def _validate_cross_field_ranges(self) -> "MapQuery":
        # Delegation, not duplication: SearchQuery owns every cross-field rule
        # (inverted dates, priority-score ranges, partial/inverted bbox).
        self.to_search_query()
        return self


class MapReportItem(BaseModel):
    """One geoprojected report, suitable for an interactive map marker.

    Deliberately omits original text, reporter identity and evidence for
    operational hygiene; every point keeps traceability to the source report
    id. location_status preserves the Phase 5 status of the report
    (UNCERTAIN stays UNCERTAIN); location_confidence is whatever the geocoding
    provider actually supplied, and null when it supplied none - it is never
    invented.
    """

    report_id: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    location_status: LocationStatus
    location_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp: datetime
    incident: str | None = None
    needs: list[NeedCategory] = Field(default_factory=list)
    priority_level: PriorityLevel | None = Field(
        default=None,
        description="Backend-computed priority level; None when the report "
        "carries no usable priority information.",
    )
    priority_score: float | None = Field(
        default=None, ge=0.0, le=100.0,
        description="Backend-computed priority final score; None when unknown.",
    )
    verification_status: VerificationStatus
    report_status: ReportStatus
    source: str | None = None


class MapResponse(BaseModel):
    """Map point response, bounded to the requested page (``limit``/``offset``).

    ``items`` holds the requested page of matching points; ``total`` is the
    full number of mappable points matching the filters, so a client pages
    through the complete set without ever materialising it in one response.
    An empty items list means simply that no report has valid coordinates (or
    none match the filters); it never implies zero humanitarian need - use the
    information-gap endpoint for that.
    """

    items: list[MapReportItem] = Field(default_factory=list)
    total: int = Field(ge=0)


class ResponseMapQuery(BaseModel):
    """Validated filters for GET /api/map/responses.

    Encodes the map-relevant subset of the Phase 12 response filters so the
    response layer and its map projection share the exact same enums. Time
    bounds follow the API convention (naive datetimes interpreted as UTC).
    """

    report_id: str | None = Field(default=None, max_length=MAX_REPORT_ID_LENGTH)
    need: NeedCategory | None = None
    response_status: ResponseStatus | None = None
    source: str | None = Field(default=None, max_length=MAX_SOURCE_LENGTH)
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(
        default=DEFAULT_LIST_LIMIT,
        ge=1,
        le=MAX_LIST_LIMIT,
        description="Maximum number of map points to return in this page "
        "(1-1000, default 100).",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of map points to skip before this page.",
    )

    @model_validator(mode="after")
    def _validate_time_range(self) -> "ResponseMapQuery":
        validate_time_range(self.start_time, self.end_time)
        return self


class ResponseMapItem(BaseModel):
    """One geoprojected response activity, suitable for a map marker.

    Only CONFIRMED, in-range, non-zero coordinates place an activity;
    UNCERTAIN or missing locations are never placed anywhere. ``location_status``
    is CONFIRMED for every point (that is the only state that geocodes); the
    underlying activity keeps its own raw ``location`` text untouched. Notes and
    affected-population details are deliberately omitted for map hygiene; the
    activity remains traceable via ``response_id``/``report_id``.
    """

    response_id: str
    report_id: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    location_status: LocationStatus
    location_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp: datetime
    need: NeedCategory | None = None
    response_status: ResponseStatus
    activity: str
    source: str | None = None


class ResponseMapResponse(BaseModel):
    """Response activities with valid coordinates, bounded to the requested
    page (``limit``/``offset``): ``items`` is one page, ``total`` the full
    mappable count. An empty list means only that no recorded activity is
    mappable (or none match); it never implies no response activity exists
    anywhere."""

    items: list[ResponseMapItem] = Field(default_factory=list)
    total: int = Field(ge=0)