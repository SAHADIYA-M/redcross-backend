"""Backend-controlled priority calculation.

The AI extracts claims (severity, population, vulnerability, time,
evidence); it NEVER computes the final priority. This module converts those
claimed values into normalized 0-100 factor scores, combines them with the
fixed weights below and derives the priority level.

Formula (weights total 100%):

    final_score =
        severity_score             * 0.30
        + affected_population_score * 0.25
        + vulnerability_score      * 0.20
        + time_sensitivity_score   * 0.15
        + evidence_verification_score * 0.10

Levels:

    85-100  -> CRITICAL
    70-84   -> HIGH
    40-69   -> MEDIUM
    0-39    -> LOW

Missing/unknown data handling (documented, deterministic):
- severity, population, vulnerability, time sensitivity are treated as
  UNKNOWN and given a neutral default (50) so an absence of a claim never
  silently inflates or deflates the score.
- a missing evidence list is treated as WEAK (low base score), never as
  strong evidence; the evidence/verification factor is deliberately capped
  because the human verification workflow does not exist yet.
- a report carrying NO usable claim at all is rejected
  (InsufficientPriorityDataError) instead of pretending facts exist.
"""

import re

from app.ai.schemas import SeverityLevel
from app.priority.schemas import PriorityLevel, PriorityResult
from app.repositories.report_repository import ReportRepository
from app.schemas.priority import PriorityResponse
from app.services.report_service import ReportNotFoundError

NEUTRAL_DEFAULT_SCORE = 50.0
CALCULATION_VERSION = "1"

WEIGHTS = {
    "severity": 0.30,
    "affected_population": 0.25,
    "vulnerability": 0.20,
    "time_sensitivity": 0.15,
    "evidence_verification": 0.10,
}

SEVERITY_SCORES = {
    SeverityLevel.CRITICAL: 100.0,
    SeverityLevel.HIGH: 75.0,
    SeverityLevel.MEDIUM: 50.0,
    SeverityLevel.LOW: 25.0,
}

_POPULATION_BANDS = (
    (0.0, 0),
    (25.0, 99),
    (50.0, 499),
    (75.0, 999),
)
_POPULATION_CAP_SCORE = 100.0

_TIME_BANDS: tuple[tuple[float, tuple[str, ...]], ...] = (
    (
        100.0,
        ("critical", "immediate", "emergency", "life-threatening", "now", "today"),
    ),
    (85.0, ("24 hour", "24 hours", "24hr", "within 24", "tomorrow")),
    (70.0, ("urgent", "48", "72", "soon", "hour", "hours")),
    (40.0, ("days", "week", "weeks")),
    (20.0, ("not urgent", "routine", "low priority", "month", "months")),
)


class InsufficientPriorityDataError(Exception):
    """Raised when a report provides no usable input for prioritization."""

    def __init__(self, report_id: str) -> None:
        self.report_id = report_id
        super().__init__(
            f"Report '{report_id}' carries no usable priority information; "
            "calculation refused rather than inventing facts"
        )


def priority_level_for_score(score: float) -> PriorityLevel:
    """Map a 0-100 score to a priority level.

    Boundaries are inclusive on the lower side (>=): 85 CRITICAL, 70 HIGH,
    40 MEDIUM, everything below 40 LOW.
    """
    if score >= 85.0:
        return PriorityLevel.CRITICAL
    if score >= 70.0:
        return PriorityLevel.HIGH
    if score >= 40.0:
        return PriorityLevel.MEDIUM
    return PriorityLevel.LOW


def calculate_priority(
    report_id: str,
    severity_score: float,
    affected_population_score: float,
    vulnerability_score: float,
    time_sensitivity_score: float,
    evidence_verification_score: float,
) -> PriorityResult:
    """Combine normalized 0-100 factor scores into a validated result.

    The final score is the weighted sum, rounded to two decimals, and the
    priority level is derived from that rounded value so the reported score
    and level always agree.
    """
    final_score = round(
        severity_score * WEIGHTS["severity"]
        + affected_population_score * WEIGHTS["affected_population"]
        + vulnerability_score * WEIGHTS["vulnerability"]
        + time_sensitivity_score * WEIGHTS["time_sensitivity"]
        + evidence_verification_score * WEIGHTS["evidence_verification"],
        2,
    )
    return PriorityResult(
        report_id=report_id,
        severity_score=severity_score,
        affected_population_score=affected_population_score,
        vulnerability_score=vulnerability_score,
        time_sensitivity_score=time_sensitivity_score,
        evidence_verification_score=evidence_verification_score,
        final_score=final_score,
        priority_level=priority_level_for_score(final_score),
        calculation_version=CALCULATION_VERSION,
    )


def severity_factor_score(
    severity: SeverityLevel | None,
) -> tuple[float, str]:
    """Convert the severity claim to a 0-100 score."""
    if severity is None:
        return (
            NEUTRAL_DEFAULT_SCORE,
            "severity not provided; neutral default applied (missing claim is "
            "unknown, not an opinion)",
        )
    return (
        SEVERITY_SCORES[severity],
        f"severity claim is {severity.value}",
    )


def affected_population_factor_score(
    population: int | None,
) -> tuple[float, str]:
    """Convert the affected population count to a 0-100 score.

    Deterministic bands; a missing count is unknown and receives the neutral
    default rather than a value.
    """
    if population is None:
        return (
            NEUTRAL_DEFAULT_SCORE,
            "affected population unknown; neutral default applied",
        )
    for score, upper in _POPULATION_BANDS:
        if population <= upper:
            return (score, f"affected population is {population}")
    return (
        _POPULATION_CAP_SCORE,
        f"affected population is {population} (1000 or more)",
    )


def vulnerability_factor_score(groups: list[str]) -> tuple[float, str]:
    """Score vulnerability from the number of distinct vulnerable groups.

    Absence of extracted groups means "unknown", not "no vulnerable people",
    so the empty case keeps the neutral default.
    """
    count = len(groups)
    if count == 0:
        return (
            NEUTRAL_DEFAULT_SCORE,
            "no vulnerable group identified; neutral default applied (absence "
            "of the claim is unknown, not 'none')",
        )
    if count == 1:
        return (60.0, "1 vulnerable group identified")
    if count == 2:
        return (80.0, "2 vulnerable groups identified")
    return (100.0, f"{count} vulnerable groups identified")


def time_sensitivity_factor_score(text: str | None) -> tuple[float, str]:
    """Score the urgency described in the free-text time-sensitivity claim.

    Deterministic keyword bands, checked in order. Unrecognized text and a
    missing claim both fall back to the neutral default.
    """
    if not text:
        return (
            NEUTRAL_DEFAULT_SCORE,
            "time sensitivity unknown; neutral default applied",
        )
    haystack = text.lower()
    for score, keywords in _TIME_BANDS:
        for keyword in keywords:
            pattern = rf"(?<!not\s)\b{re.escape(keyword)}\b" if keyword == "urgent" else rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, haystack):
                return (
                    score,
                    f"time sensitivity '{text}' matched keyword '{keyword}'",
                )
    return (
        NEUTRAL_DEFAULT_SCORE,
        f"time sensitivity '{text}' not matched by any defined rule; neutral "
        "default applied",
    )


def evidence_verification_factor_score(evidence: list[str]) -> tuple[float, str]:
    """Score evidence/verification.

    Gemini quotes in the evidence list are quotes, not verification. It is
    capped (60) because the human verification workflow does not exist yet,
    and a missing evidence list is scored as weak (10), never as strong.
    """
    count = len(evidence)
    if count == 0:
        return (
            10.0,
            "no evidence provided; missing evidence is treated as weak, not "
            "neutral and not verified",
        )
    if count == 1:
        return (
            40.0,
            "1 evidence item; verification workflow not implemented so the "
            "factor is capped",
        )
    if count == 2:
        return (
            50.0,
            "2 evidence items; verification workflow not implemented so the "
            "factor is capped",
        )
    return (
        60.0,
        f"{count} evidence items; verification workflow not implemented so "
        "the factor is capped",
    )


class PriorityService:
    """Computes deterministic backend priority for a report.

    Depends only on the ReportRepository interface so the storage layer can
    be swapped later without touching the calculation. An optional ``result_store``
    (persisted in the PostgreSQL stack) additionally stores the backend-computed
    result; when None the calculation behaves exactly as before and nothing is
    persisted. The store is only ever written by the backend — no client can
    supply a score.
    """

    def __init__(
        self,
        repository: ReportRepository,
        result_store: object | None = None,
    ) -> None:
        self._repository = repository
        self._result_store = result_store

    def calculate_for_report(self, report_id: str) -> PriorityResponse:
        report = self._repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError(report_id)
        if not report.has_priority_signal:
            raise InsufficientPriorityDataError(report_id)

        severity_score, severity_reason = severity_factor_score(report.severity)
        population_score, population_reason = affected_population_factor_score(
            report.affected_population
        )
        vulnerability_score, vulnerability_reason = vulnerability_factor_score(
            report.vulnerability
        )
        time_score, time_reason = time_sensitivity_factor_score(
            report.time_sensitivity
        )
        evidence_score, evidence_reason = evidence_verification_factor_score(
            report.evidence
        )

        result = calculate_priority(
            report_id=report_id,
            severity_score=severity_score,
            affected_population_score=population_score,
            vulnerability_score=vulnerability_score,
            time_sensitivity_score=time_score,
            evidence_verification_score=evidence_score,
        )
        payload = result.model_dump()
        payload["explanations"] = {
            "severity": severity_reason,
            "affected_population": population_reason,
            "vulnerability": vulnerability_reason,
            "time_sensitivity": time_reason,
            "evidence_verification": evidence_reason,
        }
        payload["source_values"] = {
            "severity": report.severity.value if report.severity else None,
            "affected_population": report.affected_population,
            "vulnerability": list(report.vulnerability),
            "time_sensitivity": report.time_sensitivity,
            "evidence": list(report.evidence),
        }
        response = PriorityResponse(**payload)
        if self._result_store is not None:
            self._result_store.save(result)
        return response

    def recalculate_for_report(self, report_id: str) -> PriorityResponse | None:
        """Recompute and persist the stored priority result for a report.

        Reused by the report-update path so an edit that changes priority input
        can never leave a stale stored result behind. When the report no longer
        carries usable priority input the stored result is invalidated
        (removed) instead of being forced to a fabricated value.
        """
        try:
            return self.calculate_for_report(report_id)
        except InsufficientPriorityDataError:
            self.invalidate_for_report(report_id)
            return None

    def invalidate_for_report(self, report_id: str) -> None:
        """Drop any stored priority result for a report that lost its input.

        The result store is optional (only the PostgreSQL stack persists
        results); when it cannot delete, invalidation is a no-op and the next
        backend calculation remains the single source of truth.
        """
        store = self._result_store
        if store is None:
            return
        delete = getattr(store, "delete_by_report", None)
        if delete is not None:
            delete(report_id)