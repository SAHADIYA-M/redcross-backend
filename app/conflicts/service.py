from app.conflicts.detection import are_related, find_conflicts
from app.conflicts.schemas import PotentialConflict
from app.repositories.report_repository import ReportRepository
from app.schemas.conflict import ConflictDetectionResponse
from app.services.report_service import ReportNotFoundError


class ConflictDetectionService:
    """Identifies reports holding contradictory structured claims.

    Conflicts are reported as POTENTIAL_CONFLICT for human review. The service
    never resolves, merges, deletes or overwrites any report.
    """

    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def detect_conflicts(self, report_id: str) -> ConflictDetectionResponse:
        """Return all potential conflicts between a report and others.

        The report itself is excluded, and comparisons run in sorted order for
        deterministic output. Results are ordered by how many claims conflict.
        """
        target = self._repository.get_by_id(report_id)
        if target is None:
            raise ReportNotFoundError(report_id)

        potential: list[PotentialConflict] = []
        for other in sorted(self._repository.get_all(), key=lambda r: r.id):
            if other.id == report_id:
                continue
            if not are_related(target, other):
                continue
            claims = find_conflicts(target, other)
            if claims:
                potential.append(
                    PotentialConflict(
                        related_report_id=other.id,
                        conflicts=claims,
                    )
                )

        potential.sort(
            key=lambda p: len(p.conflicts),
            reverse=True,
        )
        return ConflictDetectionResponse(
            report_id=report_id,
            potential_conflicts=potential,
        )