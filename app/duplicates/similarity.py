import re
from typing import NamedTuple

from app.duplicates.schemas import MatchingFactor
from app.location.schemas import LocationStatus
from app.models.report import Report

# --------------------------------------------------------------------------
# Factor weights (documented for explainability).
#
# Weights reflect how much each signal should matter when both reports
# provide that information. They intentionally favour the strongest evidence:
#   LOCATION   0.30  same place is strong, but never sufficient alone
#   INCIDENT   0.20  same incident type is informative
#   TEXT       0.20  wording overlap supports the same event
#   TIME       0.15  temporal closeness supports the same event
#   NEED       0.15  shared needs support the same situation
# --------------------------------------------------------------------------

FACTOR_WEIGHTS: dict[MatchingFactor, float] = {
    MatchingFactor.LOCATION: 0.30,
    MatchingFactor.INCIDENT: 0.20,
    MatchingFactor.TEXT: 0.20,
    MatchingFactor.TIME: 0.15,
    MatchingFactor.NEED: 0.15,
}

# A factor "matches" when its similarity is at or above its threshold.
FACTOR_MATCH_THRESHOLDS: dict[MatchingFactor, float] = {
    MatchingFactor.LOCATION: 0.5,
    MatchingFactor.INCIDENT: 0.5,
    MatchingFactor.TEXT: 0.5,
    MatchingFactor.TIME: 0.75,
    MatchingFactor.NEED: 0.5,
}

# Overall score required for a potential duplicate.
SCORE_THRESHOLD = 0.55
# Minimum number of matching factors (location alone is never enough).
MIN_MATCHING_FACTORS = 2
# A near-identical text is a strong enough single signal.
STRONG_TEXT_THRESHOLD = 0.85

# Reports closer than this many hours are considered temporally related.
TIME_WINDOW_HOURS = 72.0

_STOPWORDS = frozenset(
    {
        "the", "an", "is", "are", "was", "were", "near", "at", "in",
        "on", "of", "and", "to", "for", "with", "there", "has", "have",
    }
)


class DuplicateAnalysis(NamedTuple):
    """Similarity result for a pair of reports."""

    score: float
    matching_factors: list[MatchingFactor]
    text_similarity: float | None = None
    locations_conflict: bool = False


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _stem(token: str) -> str:
    """Light suffix stripping so word forms like flood/flooding/flooded match."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > 4 and token.endswith(suffix):
            stem = token[: -len(suffix)]
            if len(stem) >= 3 and stem.endswith(("i", "e")):
                stem = stem[:-1]
            return stem
    return token


def _stemmed_tokens(text: str) -> set[str]:
    return {_stem(w) for w in _tokens(text)}


def location_similarity(report_a: Report, report_b: Report) -> float | None:
    """Similarity of location strings.

    Returns None when the location is missing or marked UNCERTAIN: an
    uncertain location is never treated as a confident match.
    """
    if not report_a.location or not report_b.location:
        return None
    if (
        report_a.location_status == LocationStatus.UNCERTAIN
        or report_b.location_status == LocationStatus.UNCERTAIN
    ):
        return None
    return _jaccard(_tokens(report_a.location), _tokens(report_b.location))


def time_similarity(report_a: Report, report_b: Report) -> float | None:
    """Temporal closeness of report timestamps (0..1, None if missing)."""
    if report_a.timestamp is None or report_b.timestamp is None:
        return None
    diff_hours = abs(
        (report_a.timestamp - report_b.timestamp).total_seconds() / 3600.0
    )
    return max(0.0, 1.0 - diff_hours / TIME_WINDOW_HOURS)


def incident_similarity(report_a: Report, report_b: Report) -> float | None:
    """Similarity of incident descriptions (None if either is missing)."""
    if not report_a.incident or not report_b.incident:
        return None
    return _jaccard(
        _stemmed_tokens(report_a.incident), _stemmed_tokens(report_b.incident)
    )


def need_similarity(report_a: Report, report_b: Report) -> float | None:
    """Overlap of validated need categories (None if either is empty).

    No data must not look like a perfect match, so identical-but-empty need
    lists are treated as unavailable rather than a strong signal.
    """
    if not report_a.needs or not report_b.needs:
        return None
    a = set(report_a.needs)
    b = set(report_b.needs)
    return _jaccard(a, b)


def text_similarity(report_a: Report, report_b: Report) -> float | None:
    """Token overlap of the original report text (None if either is empty)."""
    if not report_a.original_text.strip() or not report_b.original_text.strip():
        return None
    return _jaccard(
        _stemmed_tokens(report_a.original_text),
        _stemmed_tokens(report_b.original_text),
    )


def analyze(report_a: Report, report_b: Report) -> DuplicateAnalysis:
    """Combine the available signals into a similarity score.

    Only factors with data on BOTH reports contribute: missing information is
    neither assumed to match nor penalised. Matching factors and the score are
    returned so callers can explain why a pair was flagged.
    """
    factors: dict[MatchingFactor, float] = {}
    for factor, value in (
        (MatchingFactor.LOCATION, location_similarity(report_a, report_b)),
        (MatchingFactor.TIME, time_similarity(report_a, report_b)),
        (MatchingFactor.INCIDENT, incident_similarity(report_a, report_b)),
        (MatchingFactor.NEED, need_similarity(report_a, report_b)),
        (MatchingFactor.TEXT, text_similarity(report_a, report_b)),
    ):
        if value is not None:
            factors[factor] = value

    # Two reports with strongly different confirmed locations must not be
    # flagged: "flooding in Village A" vs "flooding in Village B" are not
    # duplicates just because both involve flooding.
    location_value = factors.get(MatchingFactor.LOCATION)
    locations_conflict = (
        location_value is not None
        and location_value < FACTOR_MATCH_THRESHOLDS[MatchingFactor.LOCATION]
    )

    if not factors:
        return DuplicateAnalysis(score=0.0, matching_factors=[], text_similarity=None)

    total_weight = sum(FACTOR_WEIGHTS[f] for f in factors)
    score = (
        sum(FACTOR_WEIGHTS[f] * value for f, value in factors.items())
        / total_weight
    )
    matching = [
        f
        for f, value in factors.items()
        if value >= FACTOR_MATCH_THRESHOLDS[f]
    ]
    return DuplicateAnalysis(
        score=round(score, 3),
        matching_factors=[f for f in MatchingFactor if f in matching],
        text_similarity=factors.get(MatchingFactor.TEXT),
        locations_conflict=locations_conflict,
    )


def is_potential_duplicate(analysis: DuplicateAnalysis) -> bool:
    """Decide whether a pair qualifies as a potential duplicate (POTENTIAL, never final).

    Rules (documented for explainability):
    1. If the two confirmed locations clearly disagree, the pair is NOT a
       duplicate — "flooding" in two different villages is two incidents.
    2. Near-identical text is strong enough on its own, even when other
       signals are missing (e.g. a report submitted twice verbatim).
    3. Score must reach SCORE_THRESHOLD.
    4. Otherwise at least MIN_MATCHING_FACTORS factors matched AND the
       INCIDENT factor matched: two reports describing the same event in
       their own words are a potential duplicate. A matching LOCATION (or
       NEED, or TIME) alone is never sufficient.
    """
    if analysis.locations_conflict:
        return False
    if analysis.text_similarity is not None and analysis.text_similarity >= STRONG_TEXT_THRESHOLD:
        return True
    if analysis.score < SCORE_THRESHOLD:
        return False
    if len(analysis.matching_factors) < MIN_MATCHING_FACTORS:
        return False
    return MatchingFactor.INCIDENT in analysis.matching_factors