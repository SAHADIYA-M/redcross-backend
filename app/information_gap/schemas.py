"""Domain models for the Phase 11 information-gap detection API.

PURPOSE - this is an information-quality indicator, not a ground-truth need
assessment and not a humanitarian priority. The service answers "how much can
we trust what we (don't) know about this area?", never "how much need does
this area have?". The two concepts are kept structurally separate:

  PRIORITY SCORE      -> urgency of REPORTED needs (Phase 8).
  INFORMATION GAP     -> uncertainty/lack of sufficient information.

A zero-report area therefore yields INSUFFICIENT_INFORMATION and NEVER a low
need or low priority conclusion, because "no reports" can mean no connectivity,
no field presence, underreporting, access problems or communication failure.

Geographic unit: a simple equirectangular grid of square cells (cell_size
degrees, default 0.05 ~ 5.5 km). No external GIS or administrative boundary
dataset is used in this phase.
"""

from datetime import datetime
from enum import Enum
from math import ceil, floor

from pydantic import BaseModel, Field, model_validator

from app.utils.validators import validate_bbox

DEFAULT_CELL_SIZE = 0.05
MIN_CELL_SIZE = 0.01
MAX_CELL_SIZE = 1.0

# Upper bound on grid cells a single analysis may enumerate. Enumerating a
# whole country at MIN_CELL_SIZE would create hundreds of millions of cells,
# so oversized boxes are rejected with a client error instead of silently
# truncating (silent truncation could hide information gaps).
MAX_INFORMATION_GAP_CELLS = 10_000


def overlapping_cell_count(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    size: float,
) -> int:
    """Number of grid cells that ``cells_overlapping`` would enumerate.

    Uses the exact same anchor-and-step arithmetic as the grid enumeration so
    a validation cap never disagrees with the produced grid. Degenerate boxes
    (min == max) yield 0 because every candidate cell is skipped.
    """
    first_lat = floor(min_lat / size) * size
    lat_count = 0
    for lat_index in range(0, ceil((max_lat - first_lat) / size) + 1):
        lat = round(first_lat + lat_index * size, 6)
        if lat >= max_lat:
            continue
        lat_count += 1
    first_lon = floor(min_lon / size) * size
    lon_count = 0
    for lon_index in range(0, ceil((max_lon - first_lon) / size) + 1):
        lon = round(first_lon + lon_index * size, 6)
        if lon >= max_lon:
            continue
        lon_count += 1
    return lat_count * lon_count


class InformationGapStatus(str, Enum):
    """Information sufficiency of an area (heuristic, MVP thresholds).

    SUFFICIENT_INFORMATION   - enough recent, diverse, verifiable data exists
                               that the absence of further reporting is not
                               itself a strong signal.
    LIMITED_INFORMATION      - some data exists but with meaningful gaps
                               (staleness, low diversity, low verification).
    INSUFFICIENT_INFORMATION - too little trustworthy information to assess
                               needs; further assessment is recommended.

    These thresholds are transparent MVP heuristics, NOT scientifically
    validated ground-truth assessments.
    """

    SUFFICIENT_INFORMATION = "SUFFICIENT_INFORMATION"
    LIMITED_INFORMATION = "LIMITED_INFORMATION"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class InformationGapQuery(BaseModel):
    """Parameters for GET /api/map/information-gaps.

    The analysis bounds are optional. With no bounding box the service returns
    a cell for every area that holds at least one geocodable report. Supplying
    a bounding box additionally enumerates EVERY cell inside the box, so areas
    with zero reports are surfaced explicitly (report_count=0,
    INSUFFICIENT_INFORMATION) instead of disappearing.
    """

    min_lat: float | None = Field(
        default=None, ge=-90.0, le=90.0,
        description="Southern latitude of the analysis area (-90..90).",
    )
    max_lat: float | None = Field(
        default=None, ge=-90.0, le=90.0,
        description="Northern latitude of the analysis area (-90..90).",
    )
    min_lon: float | None = Field(
        default=None, ge=-180.0, le=180.0,
        description="Western longitude of the analysis area (-180..180).",
    )
    max_lon: float | None = Field(
        default=None, ge=-180.0, le=180.0,
        description="Eastern longitude of the analysis area (-180..180).",
    )
    cell_size: float = Field(
        default=DEFAULT_CELL_SIZE,
        ge=MIN_CELL_SIZE,
        le=MAX_CELL_SIZE,
        description="Grid cell size in degrees (0.01-1.0).",
    )

    @property
    def has_bounding_box(self) -> bool:
        """True when a complete analysis bounding box was supplied."""
        return None not in (self.min_lat, self.max_lat, self.min_lon, self.max_lon)

    @model_validator(mode="after")
    def _validate_bounding_box(self) -> "InformationGapQuery":
        validate_bbox(
            self.min_lat,
            self.max_lat,
            self.min_lon,
            self.max_lon,
            missing_message=(
                "min_lat, max_lat, min_lon and max_lon must all be supplied "
                "together to define the analysis area"
            ),
        )
        if self.has_bounding_box:
            count = overlapping_cell_count(
                self.min_lat,
                self.max_lat,
                self.min_lon,
                self.max_lon,
                self.cell_size,
            )
            if count > MAX_INFORMATION_GAP_CELLS:
                raise ValueError(
                    "Bounding box at cell_size "
                    f"{self.cell_size} would enumerate {count} grid cells; "
                    f"the maximum allowed is {MAX_INFORMATION_GAP_CELLS}"
                )
        return self


class InformationGapArea(BaseModel):
    """Information-gap analysis for one grid cell.

    ``report_count`` counts the reports with a valid resolved coordinate
    inside the cell. ``latest_report_at`` is the newest report timestamp
    (None when the cell has no reports). ``distinct_sources`` counts distinct
    non-empty report sources. ``reasons`` are deterministic, backend-generated
    explanations of which signals drove the result; they are never produced by
    an AI model.
    """

    area_id: str = Field(
        description="Deterministic cell identifier (cell:<min_lat>:<min_lon>)."
    )
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    report_count: int = Field(ge=0)
    latest_report_at: datetime | None = Field(
        default=None,
        description="Newest report timestamp in the cell; None when empty.",
    )
    distinct_sources: int = Field(ge=0)
    information_gap_score: int = Field(
        ge=0, le=100,
        description="0-100 information uncertainty; higher = greater gap. "
        "Not a humanitarian priority score.",
    )
    information_status: InformationGapStatus
    reasons: list[str] = Field(default_factory=list)


class InformationGapResponse(BaseModel):
    """The set of analyzed areas.

    An area that reports INSUFFICIENT_INFORMATION means "we do not know
    enough about this area", never "there is no need here".
    """

    areas: list[InformationGapArea] = Field(default_factory=list)
    total: int = Field(ge=0)