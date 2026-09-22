"""Domain models for the Phase 12 Response Coverage feature.

Two concepts are deliberately kept apart:

  REPORTED NEED   - what a report says people need (Phase 1-11 enums reused).
  RESPONSE ACTIVITY - a recorded action taken in response to a reported need.

RECORDING IS NOT PROOF:
A need with response_count = 0 is reported as NO_RESPONSE_RECORDED, which means
"no response activity is currently recorded in this system". It NEVER means
"nobody is responding" or "no response exists". Real-world response may be
happening that this system simply does not know about. This distinction is the
responsible way to handle absent data in a humanitarian context and is visible
in the status documentation below.

Linking (strongest available identifier): every response activity references an
existing report by ``report_id`` (validated on creation). Coverage therefore
matches response -> report -> reported need deterministically; text similarity
or heuristic matching is never used, and a response is never attached to an
arbitrary report.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.ai.schemas import NeedCategory
from app.location.schemas import LocationStatus
from app.priority.schemas import PriorityLevel
from app.schemas.lengths import (
    DEFAULT_LIST_LIMIT,
    MAX_ACTIVITY_LENGTH,
    MAX_LIST_LIMIT,
    MAX_LOCATION_LENGTH,
    MAX_NOTES_LENGTH,
    MAX_REASON_LENGTH,
    MAX_SOURCE_LENGTH,
)
from app.utils.validators import validate_time_range
from app.verification.schemas import VerificationStatus


class ResponseStatus(str, Enum):
    """Controlled lifecycle status of a response activity.

    PLANNED     - the activity is recorded and planned; action has not yet
                  started. It is still a recorded response activity and counts
                  as RESPONSE_RECORDED for coverage, with its distinct status
                  keeping "not yet underway" explicit.
    IN_PROGRESS - the activity is underway.
    COMPLETED   - the activity has been completed.
    CANCELLED   - the activity will not proceed. CANCELLED activities are
                  preserved for traceability but are NEVER counted as coverage.

    The enum is deliberately small (shorthand per the MVP); there are no extra
    statuses.
    """

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CoverageStatus(str, Enum):
    """Controlled coverage status of a reported need.

    RESPONSE_RECORDED        - at least one non-cancelled response activity is
                               recorded in this system for this need.
    NO_RESPONSE_RECORDED     - no response activity is recorded in this system
                               for this need. This is about what is *recorded*;
                               it does NOT mean nobody is responding and does
                               NOT mean no response exists.
    PARTIAL_RESPONSE_RECORDED- quantitative data shows the reported population
                               is only partially reached by recorded response
                               activities (computed only when both the reported
                               population and a reached count are available).
    UNKNOWN                  - the link between a response and a reported need
                               cannot be determined. Never guessed. In the MVP
                               responses are always attached to a report by id,
                               so this cannot currently occur; it is defined so
                               a future unlinked-response scenario degrades
                               safely instead of guessing.
    """

    RESPONSE_RECORDED = "RESPONSE_RECORDED"
    NO_RESPONSE_RECORDED = "NO_RESPONSE_RECORDED"
    PARTIAL_RESPONSE_RECORDED = "PARTIAL_RESPONSE_RECORDED"
    UNKNOWN = "UNKNOWN"


class ResponseActivity(BaseModel):
    """One recorded response activity.

    ``response_id`` is the stable identity preserved across status updates
    (PATCH changes status, never identity). ``report_id`` is required so every
    recorded activity can be traced back to the report/need it addresses.
    ``need`` is optional: when set, the activity addresses that specific
    reported need (per-need coverage matching); when None the activity is a
    general response to the report and is never counted as coverage for a
    specific need (the system does not guess which need it served).
    ``affected_population`` is the number of people/households reported reached;
    it is optional and only used for quantitative coverage when the reported
    need also carries an affected population count.
    """

    response_id: str
    report_id: str
    need: NeedCategory | None = Field(
        default=None,
        description=(
            "Specific reported need this activity addresses; None means a "
            "general (need-unspecific) response."
        ),
    )
    activity: str
    response_status: ResponseStatus
    timestamp: datetime
    location: str | None = None
    source: str | None = None
    notes: str | None = None
    affected_population: int | None = Field(default=None, ge=0)


class CreateResponse(BaseModel):
    """Input schema for POST /api/responses.

    ``report_id`` is validated against the reports repository: a response must
    reference a real report, never an arbitrary one. ``activity`` describes what
    was done (free text; no invented taxonomy). ``response_status`` defaults to
    PLANNED so a recorded-but-not-started activity is the safe default.
    """

    report_id: str = Field(min_length=1)
    need: NeedCategory | None = None
    activity: str = Field(min_length=1, max_length=MAX_ACTIVITY_LENGTH)
    response_status: ResponseStatus = ResponseStatus.PLANNED
    timestamp: datetime | None = None
    location: str | None = Field(default=None, max_length=MAX_LOCATION_LENGTH)
    source: str | None = Field(default=None, max_length=MAX_SOURCE_LENGTH)
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH)
    affected_population: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _strip_text(self) -> "CreateResponse":
        self.activity = self.activity.strip()
        if not self.activity:
            raise ValueError("activity must not be blank")
        return self


class UpdateResponse(BaseModel):
    """Input schema for PATCH /api/responses/{response_id}.

    Preserves activity identity: report_id, need and response_id cannot be
    changed (a response is traced to the report/need it was created for). A
    status change is the important lifecycle event and is written to the Phase 9
    append-only audit log; other benign edits (activity/notes/population) update
    the activity in place. ``actor_id``/``reason`` are forwarded to the audit
    record so the change stays traceable to a person.
    """

    response_status: ResponseStatus | None = None
    activity: str | None = Field(
        default=None, min_length=1, max_length=MAX_ACTIVITY_LENGTH
    )
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH)
    affected_population: int | None = Field(default=None, ge=0)
    actor_id: str | None = None
    reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _require_change(self) -> "UpdateResponse":
        if (
            self.response_status is None
            and self.activity is None
            and self.notes is None
            and self.affected_population is None
        ):
            raise ValueError("at least one editable field must be supplied")
        if self.activity is not None and not self.activity.strip():
            raise ValueError("activity must not be blank")
        return self


class ResponseQuery(BaseModel):
    """Validated filters for GET /api/responses.

    All filters are optional and combined with AND. Datetimes follow the API
    convention (naive values interpreted as UTC). Results are returned newest
    first. ``need`` matches the response's specific need; ``source`` and
    ``location`` are case-insensitive substrings on the response fields.
    """

    report_id: str | None = None
    need: NeedCategory | None = None
    response_status: ResponseStatus | None = None
    source: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_time_range(self) -> "ResponseQuery":
        validate_time_range(self.start_time, self.end_time)
        return self


def coverage_semantics_doc() -> str:
    """Shared OpenAPI description for the coverage endpoint semantics."""
    return (
        "Compares REPORTED NEEDS against RECORDED response activities "
        "(independent of the Phase 11 information-gap analysis). "
        "NO_RESPONSE_RECORDED means no response activity is recorded in this "
        "system for that need - it does NOT mean nobody is responding and does "
        "NOT mean no response exists. An empty items list means there are no "
        "reported needs matching the filters; it never implies there is no "
        "humanitarian need."
    )


class CoverageQuery(BaseModel):
    """Validated filters for GET /api/analytics/response-coverage.

    Every filter reuses existing enums. ``need`` restricts the output to rows
    for that reported need category; ``priority``/``verification_status`` reuse
    the Phase 8/9 definitions so a CRITICAL-unverified need stays clearly
    visible (never hidden, never conflated with coverage).
    """

    need: NeedCategory | None = None
    report_id: str | None = None
    priority: PriorityLevel | None = None
    verification_status: VerificationStatus | None = None


class CoverageItem(BaseModel):
    """Coverage row for one reported need of one report.

    ``priority_level``/``priority_score`` are the Phase 8 backend-computed
    values (None when the report carries no usable priority information - never
    coerced). ``verification_status`` is preserved unchanged, so an UNVERIFIED
    need + NO_RESPONSE_RECORDED stays visibly different from a VERIFIED one.
    ``location_status`` preserves the Phase 5 status (UNCERTAIN stays
    UNCERTAIN); coordinates are never invented here - use the map endpoints for
    points. ``coverage_percentage`` is only present when the reported
    population AND a reached count are actually available; otherwise it stays
    None and categorical coverage is reported instead.
    """

    report_id: str
    need: NeedCategory
    priority_level: PriorityLevel | None = None
    priority_score: float | None = Field(default=None, ge=0.0, le=100.0)
    verification_status: VerificationStatus
    location: str | None = None
    location_status: LocationStatus | None = None
    response_status: CoverageStatus
    response_count: int = Field(
        ge=0,
        description=(
            "Number of non-cancelled response activities recorded against this "
            "reported need."
        ),
    )
    coverage_percentage: float | None = Field(
        default=None, ge=0.0, le=100.0,
        description=(
            "Quantitative coverage (reached / reported population) only when "
            "both values are actually available; None otherwise."
        ),
    )
    latest_response_at: datetime | None = None
    active_response_statuses: list[ResponseStatus] = Field(default_factory=list)


class CoverageResponse(BaseModel):
    """Response for the coverage endpoint.

    The semantic markers are embedded here: a row is never called "no response
    exists" or "unmet need"; it is NO_RESPONSE_RECORDED. An empty result never
    implies zero humanitarian need (information sufficiency lives in the Phase
    11 information-gap endpoint and is NEVER combined with coverage).
    """

    items: list[CoverageItem] = Field(default_factory=list)
    total: int = Field(ge=0)