from app.models.report import Report
from app.repositories.report_repository import ReportRepository


class InMemoryReportRepository(ReportRepository):
    """Temporary repository backed by an in-memory dictionary.

    Replaced by a PostgreSQL-backed repository in a later phase.
    """

    def __init__(self) -> None:
        self._store: dict[str, Report] = {}

    def create(self, report: Report) -> Report:
        self._store[report.id] = report
        return report

    def get_by_id(self, report_id: str) -> Report | None:
        return self._store.get(report_id)

    def get_all(self) -> list[Report]:
        return list(self._store.values())

    def get_cluster_candidates(self, location: str, need: str) -> list[Report]:
        return [
            report
            for report in self._store.values()
            if report.cluster_location == location and report.cluster_need == need
        ]

    def update(self, report_id: str, report: Report) -> Report | None:
        if report_id not in self._store:
            return None
        self._store[report_id] = report
        return report