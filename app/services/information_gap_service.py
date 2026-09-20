"""Phase 11 information-gap detection.

PURPOSE
The service answers: "how much can we trust what we (don't) know about an
area?" It NEVER answers "how much need is there?" - that would wrongly treat
absence of reports as absence of need. A lack of reports can mean poor
connectivity, difficult access, underreporting, no field presence,
communication failure or any other information gap. Zero reports therefore
always yields INSUFFICIENT_INFORMATION, never LOW need or LOW priority.

GEOGRAPHIC UNIT
A simple equirectangular grid of square cells (cell_size degrees, default
0.05 ~ 5.5 km). No external GIS, administrative-boundary dataset or external
map service is used in this phase. Each report is placed in the cell of its
resolved coordinate; reports without a CONFIRMED non-zero coordinate are not
placed in any cell (they cannot be located, which is itself a gap signal).

SCORING (0-100, higher = greater information uncertainty/gap)
A transparent deterministic weighted heuristic over the actual data:

    recency               x 0.30   (stale or missing data is a worse gap)
    report_count          x 0.20   (very few reports is a limitation)
    source_diversity      x 0.20   (one source is not independent
                                    confirmation; five reports from one
                                    source are not five independent accounts)
    verification_coverage x 0.20   (REJECTED/UNCERTAIN/UNVERIFIED reports are
                                    never counted as verified evidence)
    location_uncertainty  x 0.10   (UNCERTAIN or unset location status is a
                                    quality limitation, never silent)

Factor mappings and a note on thresholds are documented inline below. These
are transparent MVP heuristics, NOT scientifically validated assessments.
Information-gap score is deliberately kept separate from the Phase 8 priority
score (need urgency); the two are never combined.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.information_gap.schemas import (
    DEFAULT_CELL_SIZE,
    InformationGapArea,
    InformationGapQuery,
    InformationGapResponse,
    InformationGapStatus,
)
from app.location.projection import resolve_confirmed_point
from app.location.schemas import LocationStatus
from app.location.service import LocationService
from app.models.report import Report
from app.repositories.report_repository import ReportRepository
from app.utils.datetime_utils import as_utc
from app.verification.schemas import VerificationStatus

# ------------------------------------------------------------- score weights

RECENCY_WEIGHT = 0.30
COUNT_WEIGHT = 0.20
SOURCE_WEIGHT = 0.20
VERIFICATION_WEIGHT = 0.20
LOCATION_WEIGHT = 0.10

INSUFFICIENT_SCORE = 75
LIMITED_SCORE = 45

EMPTY_CELL_SCORE = 100
EMPTY_CELL_REASON = "No reports available for this area."


def _days_between(latest: datetime, now: datetime) -> float:
    """Age of the newest report, in days, as a non-negative float."""
    return max(0.0, (now - as_utc(latest)).total_seconds() / 86400.0)


# ---------------------------------------------------------------- cell grid

@dataclass(frozen=True)
class GridCell:
    """A square grid cell anchored at its south-west corner."""

    min_lat: float
    min_lon: float
    size: float

    @property
    def max_lat(self) -> float:
        return round(self.min_lat + self.size, 6)

    @property
    def max_lon(self) -> float:
        return round(self.min_lon + self.size, 6)

    @property
    def area_id(self) -> str:
        return f"cell:{self.min_lat}:{self.min_lon}"


def grid_cell_anchor(latitude: float, longitude: float, size: float) -> GridCell:
    """Return the grid cell containing the given coordinate."""
    min_lat = round(math.floor(latitude / size) * size, 6)
    min_lon = round(math.floor(longitude / size) * size, 6)
    return GridCell(min_lat=min_lat, min_lon=min_lon, size=size)


def cells_overlapping(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    size: float,
) -> list[GridCell]:
    """Every grid cell that overlaps the supplied bounding box."""
    cells: list[GridCell] = []
    first_lat = math.floor(min_lat / size) * size
    for lat_index in range(0, math.ceil((max_lat - first_lat) / size) + 1):
        lat = round(first_lat + lat_index * size, 6)
        if lat >= max_lat:
            continue
        first_lon = math.floor(min_lon / size) * size
        for lon_index in range(0, math.ceil((max_lon - first_lon) / size) + 1):
            lon = round(first_lon + lon_index * size, 6)
            if lon >= max_lon:
                continue
            cells.append(GridCell(min_lat=lat, min_lon=lon, size=size))
    return cells


# ------------------------------------------------------- signal factor scores

def recency_factor_score(latest_report_at: datetime | None, now: datetime) -> float:
    """Staleness factor. Missing timestamps are not "recent": they score the
    worst bucket, matching an area with no fresh data at all."""
    if latest_report_at is None:
        return 100.0
    days = _days_between(latest_report_at, now)
    if days <= 1.0:
        return 0.0
    if days <= 3.0:
        return 25.0
    if days <= 7.0:
        return 50.0
    if days <= 30.0:
        return 75.0
    return 100.0


def report_count_factor_score(report_count: int) -> float:
    """Very few reports mean very little signal; zero means no signal."""
    if report_count <= 0:
        return 100.0
    if report_count == 1:
        return 70.0
    if report_count <= 4:
        return 50.0
    if report_count <= 9:
        return 30.0
    return 0.0


def source_diversity_factor_score(distinct_sources: int) -> float:
    """Multiple reports from one source are not independent confirmation."""
    if distinct_sources == 0:
        return 85.0  # no source information at all
    if distinct_sources == 1:
        return 70.0
    if distinct_sources == 2:
        return 40.0
    return 0.0


def verification_coverage_factor_score(verified_ratio: float) -> float:
    """Coverage of human verification. REJECTED and UNCERTAIN reports are
    never counted as verified evidence."""
    if verified_ratio >= 0.7:
        return 15.0
    if verified_ratio >= 0.4:
        return 45.0
    if verified_ratio > 0.0:
        return 70.0
    return 90.0


def location_uncertainty_factor_score(uncertain_ratio: float) -> float:
    """Share of reports whose location status is not CONFIRMED."""
    if uncertain_ratio >= 0.5:
        return 85.0
    if uncertain_ratio > 0.0:
        return 60.0
    return 0.0


def information_status_for_score(score: int) -> InformationGapStatus:
    """Map the 0-100 gap score onto a status band.

    Thresholds (>= 75 INSUFFICIENT, >= 45 LIMITED, below SUFFICIENT) are
    transparent MVP heuristics, not validated ground truth.
    """
    if score >= INSUFFICIENT_SCORE:
        return InformationGapStatus.INSUFFICIENT_INFORMATION
    if score >= LIMITED_SCORE:
        return InformationGapStatus.LIMITED_INFORMATION
    return InformationGapStatus.SUFFICIENT_INFORMATION


# -------------------------------------------------------------- explanations

def build_reasons(
    *,
    report_count: int,
    recency: float,
    distinct_sources: int,
    verified_ratio: float,
    uncertain_ratio: float,
) -> list[str]:
    """Deterministic, data-backed reasons. Never generated by an AI model."""
    reasons: list[str] = []
    if recency >= 75.0:
        reasons.append("No recent reports")
    elif recency > 0.0:
        reasons.append("Reports are not recent")
    if report_count < 5:
        reasons.append("Few reports")
    if distinct_sources == 0:
        reasons.append("No source information available")
    elif distinct_sources == 1:
        reasons.append("Reports come from only one source")
    if verified_ratio == 0.0:
        reasons.append("No verified reports")
    elif verified_ratio < 0.5:
        reasons.append("Most reports are unverified")
    elif verified_ratio < 0.7:
        reasons.append("Many reports are unverified")
    if uncertain_ratio >= 0.5:
        reasons.append("Many reports have uncertain locations")
    elif uncertain_ratio > 0.0:
        reasons.append("Some reports have uncertain locations")
    return reasons


class InformationGapService:
    """Computes per-cell information sufficiency from existing report data.

    Depends only on the ReportRepository interface (so the storage layer can
    be swapped for PostgreSQL later) and the Phase 5 LocationService. The
    reference clock can be injected for deterministic tests.
    """

    def __init__(
        self,
        repository: ReportRepository,
        location_service: LocationService,
        now: datetime | None = None,
    ) -> None:
        self._repository = repository
        self._location_service = location_service
        self._now = now

    def analyze(self, query: InformationGapQuery) -> InformationGapResponse:
        """Analyze every cell in scope and return the gap areas.

        Scope: with a bounding box, every overlapping cell is analyzed (empty
        cells included, so "no reports" becomes INSUFFICIENT_INFORMATION
        instead of vanishing). Without one, only cells that actually contain a
        geocodable report are analyzed.
        """
        now = self._now or datetime.now(timezone.utc)
        size = query.cell_size

        reports_by_cell: dict[GridCell, list[Report]] = {}
        for report in self._repository.get_all():
            cell = self._cell_for(report, size)
            if cell is not None:
                reports_by_cell.setdefault(cell, []).append(report)

        cells = self._cells_in_scope(query, reports_by_cell)
        areas = [
            self._analyze_cell(cell, reports_by_cell.get(cell, []), now)
            for cell in cells
        ]
        areas.sort(key=lambda area: area.area_id)
        return InformationGapResponse(areas=areas, total=len(areas))

    # ------------------------------------------------------------- internals

    def _cell_for(self, report: Report, size: float) -> GridCell | None:
        """Resolve a report to its grid cell, or None when not placeable.

        Only CONFIRMED, in-range, non-zero coordinates place a report. A
        report with no resolvable location is not stuck on the map anywhere;
        it simply has no known position.
        """
        point = resolve_confirmed_point(report.location, self._location_service)
        if point is None:
            return None
        lat, lng, _ = point
        return grid_cell_anchor(lat, lng, size)

    @staticmethod
    def _cells_in_scope(
        query: InformationGapQuery,
        reports_by_cell: dict[GridCell, list[Report]],
    ) -> list[GridCell]:
        if query.has_bounding_box:
            return cells_overlapping(
                query.min_lat,
                query.max_lat,
                query.min_lon,
                query.max_lon,
                query.cell_size,
            )
        return sorted(reports_by_cell.keys(), key=lambda cell: cell.area_id)

    def _analyze_cell(
        self,
        cell: GridCell,
        reports: list[Report],
        now: datetime,
    ) -> InformationGapArea:
        base = InformationGapArea(
            area_id=cell.area_id,
            min_lat=cell.min_lat,
            max_lat=cell.max_lat,
            min_lon=cell.min_lon,
            max_lon=cell.max_lon,
            report_count=0,
            latest_report_at=None,
            distinct_sources=0,
            information_gap_score=EMPTY_CELL_SCORE,
            information_status=InformationGapStatus.INSUFFICIENT_INFORMATION,
            reasons=[EMPTY_CELL_REASON],
        )
        report_count = len(reports)
        if report_count == 0:
            return base

        latest = max(
            (report.timestamp for report in reports if report.timestamp is not None),
            default=None,
        )
        distinct_sources = len(
            {report.source for report in reports if report.source and report.source.strip()}
        )
        verified_count = sum(
            1
            for report in reports
            if report.verification_status == VerificationStatus.VERIFIED
        )
        uncertain_count = sum(
            1
            for report in reports
            if report.location_status != LocationStatus.CONFIRMED
        )

        recency = recency_factor_score(latest, now)
        count_factor = report_count_factor_score(report_count)
        source_factor = source_diversity_factor_score(distinct_sources)
        verified_ratio = verified_count / report_count
        uncertain_ratio = uncertain_count / report_count
        verification_factor = verification_coverage_factor_score(verified_ratio)
        location_factor = location_uncertainty_factor_score(uncertain_ratio)

        score = round(
            recency * RECENCY_WEIGHT
            + count_factor * COUNT_WEIGHT
            + source_factor * SOURCE_WEIGHT
            + verification_factor * VERIFICATION_WEIGHT
            + location_factor * LOCATION_WEIGHT
        )

        reasons = build_reasons(
            report_count=report_count,
            recency=recency,
            distinct_sources=distinct_sources,
            verified_ratio=verified_ratio,
            uncertain_ratio=uncertain_ratio,
        )

        return InformationGapArea(
            area_id=cell.area_id,
            min_lat=cell.min_lat,
            max_lat=cell.max_lat,
            min_lon=cell.min_lon,
            max_lon=cell.max_lon,
            report_count=report_count,
            latest_report_at=latest,
            distinct_sources=distinct_sources,
            information_gap_score=score,
            information_status=information_status_for_score(score),
            reasons=reasons,
        )


__all__ = [
    "DEFAULT_CELL_SIZE",
    "InformationGapService",
    "GridCell",
    "grid_cell_anchor",
    "cells_overlapping",
    "recency_factor_score",
    "report_count_factor_score",
    "source_diversity_factor_score",
    "verification_coverage_factor_score",
    "location_uncertainty_factor_score",
    "information_status_for_score",
    "build_reasons",
    "InformationGapStatus",
]