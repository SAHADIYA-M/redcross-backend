from app.duplicates.schemas import PotentialDuplicate
from app.duplicates.similarity import (
    analyze,
    is_potential_duplicate,
)
from app.repositories.report_repository import ReportRepository
from app.schemas.duplicate import DuplicateDetectionResponse
from app.services.report_service import ReportNotFoundError


class DuplicateDetectionService:
    """Identifies reports that *may* describe the same incident.

    Detection only produces POTENTIAL_DUPLICATE relationships for human
    review. It never deletes, merges or overwrites any report.
    """

    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def detect_duplicates(self, report_id: str) -> DuplicateDetectionResponse:
        """Return all potential duplicates of the given report, by score.

        The report itself is excluded, and reports are compared in sorted
        order for deterministic output.
        """
        target = self._repository.get_by_id(report_id)
        if target is None:
            raise ReportNotFoundError(report_id)

        candidates: list[PotentialDuplicate] = []
        for other in sorted(self._repository.get_all(), key=lambda r: r.id):
            if other.id == report_id:
                continue
            analysis = analyze(target, other)
            if is_potential_duplicate(analysis):
                candidates.append(
                    PotentialDuplicate(
                        related_report_id=other.id,
                        similarity_score=analysis.score,
                        matching_factors=analysis.matching_factors,
                    )
                )

        candidates.sort(key=lambda c: c.similarity_score, reverse=True)
        return DuplicateDetectionResponse(
            report_id=report_id,
            potential_duplicates=candidates,
        )