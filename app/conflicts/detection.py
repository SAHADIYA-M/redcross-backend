from app.conflicts.schemas import ConflictingClaim
from app.duplicates.schemas import MatchingFactor
from app.duplicates.similarity import (
    STRONG_TEXT_THRESHOLD,
    analyze,
)
from app.models.report import Report

# --------------------------------------------------------------------------
# Relatedness threshold.
#
# Reports must plausibly refer to the same or a related situation before their
# claims are compared. We reuse Phase 6's signal analysis, but with a lower
# bar than duplicate detection: similarity is evidence of relatedness, while a
# potential duplicate demands much more.
# --------------------------------------------------------------------------

RELATEDNESS_SCORE_THRESHOLD = 0.4

# Relative population difference above which two counts are contradictory.
# E.g. 20 vs 3 (relative difference ~0.85) is a conflict; 20 vs 22 is not.
POPULATION_CONFLICT_RELATIVE_DIFFERENCE = 0.5


def are_related(report_a: Report, report_b: Report) -> bool:
    """Decide whether two reports plausibly refer to the same situation.

    Uses the same location/time/incident/need/text signals as Phase 6:

    - clearly conflicting confirmed locations mean the reports are about
      different places (and therefore different situations);
    - otherwise, a sufficient combined score OR a shared incident/location
      makes them "related enough" to compare claims;
    - near-identical text is always strongly related (likely same report).
    """
    analysis = analyze(report_a, report_b)
    if analysis.locations_conflict:
        return False
    if analysis.text_similarity is not None and analysis.text_similarity >= STRONG_TEXT_THRESHOLD:
        return True
    if analysis.score >= RELATEDNESS_SCORE_THRESHOLD:
        return True
    return (
        MatchingFactor.INCIDENT in analysis.matching_factors
        or MatchingFactor.LOCATION in analysis.matching_factors
    )


def _population_are_conflicting(a: int | None, b: int | None) -> bool:
    """Whether two population counts are contradictory, not just different."""
    if a is None or b is None:
        return False
    if a == b:
        return False
    larger = max(a, b)
    smaller = min(a, b)
    if larger == 0:
        return False
    return (larger - smaller) / larger >= POPULATION_CONFLICT_RELATIVE_DIFFERENCE


def find_conflicts(report_a: Report, report_b: Report) -> list[ConflictingClaim]:
    """Compare structured claims of two related reports.

    A claim only conflicts when BOTH reports carry it and the values are
    contradictory. Missing or unknown information never produces a conflict.
    """
    claims: list[ConflictingClaim] = []

    if (
        report_a.affected_population is not None
        and report_b.affected_population is not None
        and _population_are_conflicting(
            report_a.affected_population, report_b.affected_population
        )
    ):
        claims.append(
            ConflictingClaim(
                field="affected_population",
                report_a_value=report_a.affected_population,
                report_b_value=report_b.affected_population,
                reason=(
                    "Both reports state an affected population, but the counts "
                    "are contradictory."
                ),
            )
        )

    if (
        report_a.severity is not None
        and report_b.severity is not None
        and report_a.severity != report_b.severity
    ):
        claims.append(
            ConflictingClaim(
                field="severity",
                report_a_value=report_a.severity.value,
                report_b_value=report_b.severity.value,
                reason="Both reports state a severity, but the levels differ.",
            )
        )

    if (
        report_a.infrastructure_status is not None
        and report_b.infrastructure_status is not None
        and report_a.infrastructure_status != report_b.infrastructure_status
    ):
        claims.append(
            ConflictingClaim(
                field="infrastructure_status",
                report_a_value=report_a.infrastructure_status.value,
                report_b_value=report_b.infrastructure_status.value,
                reason=(
                    "Both reports state the status of infrastructure or a "
                    "service, but the statuses contradict each other."
                ),
            )
        )

    needs_conflicts = _find_need_availability_conflicts(report_a, report_b)
    claims.extend(needs_conflicts)

    return claims


def _find_need_availability_conflicts(
    report_a: Report, report_b: Report
) -> list[ConflictingClaim]:
    """A need conflict: one report reports a need, the other says it is met.

    Report A: "There is no drinking water."      -> needs: [WATER]
    Report B: "Drinking water is available."     -> available_needs: [WATER]

    A claim only conflicts when the OPPOSITE claim is explicit: a report that
    simply does not mention water is not conflicting evidence.
    """
    claims: list[ConflictingClaim] = []
    a_needs = set(report_a.needs)
    b_needs = set(report_b.needs)
    a_available = set(report_a.available_needs)
    b_available = set(report_b.available_needs)

    for category in (a_needs & b_available):
        claims.append(
            ConflictingClaim(
                field=f"need.{category.value}.availability",
                report_a_value=f"NEEDED ({category.value})",
                report_b_value=f"AVAILABLE ({category.value})",
                reason=(
                    f"Report A reports {category.value} as a need while "
                    f"report B reports it as available."
                ),
            )
        )

    for category in (b_needs & a_available):
        claims.append(
            ConflictingClaim(
                field=f"need.{category.value}.availability",
                report_a_value=f"AVAILABLE ({category.value})",
                report_b_value=f"NEEDED ({category.value})",
                reason=(
                    f"Report B reports {category.value} as a need while "
                    f"report A reports it as available."
                ),
            )
        )

    return claims