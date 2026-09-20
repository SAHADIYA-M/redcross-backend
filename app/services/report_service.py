import uuid
from datetime import datetime, timezone

from app.models.report import Report
from app.repositories.report_repository import ReportRepository
from app.schemas.report import CreateReport, UpdateReport


class ReportNotFoundError(Exception):
    """Raised when a report with the requested id does not exist."""

    def __init__(self, report_id: str) -> None:
        self.report_id = report_id
        super().__init__(f"Report '{report_id}' not found")


class ReportService:
    """Business logic for report management.

    Depends only on the ReportRepository interface, so the storage
    implementation can be swapped without changing this layer.
    """

    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def create(self, data: CreateReport) -> Report:
        report = Report(
            id=uuid.uuid4().hex,
            original_text=data.original_text,
            reporter=data.reporter,
            timestamp=data.timestamp or datetime.now(timezone.utc),
            location=data.location,
            incident=data.incident,
            evidence=data.evidence,
            status=data.status,
            source=data.source,
            needs=data.needs,
            location_status=data.location_status,
            severity=data.severity,
            affected_population=data.affected_population,
            infrastructure_status=data.infrastructure_status,
            available_needs=data.available_needs,
            vulnerability=data.vulnerability,
            time_sensitivity=data.time_sensitivity,
        )
        return self._repository.create(report)

    def get_all(self) -> list[Report]:
        return self._repository.get_all()

    def get_by_id(self, report_id: str) -> Report:
        report = self._repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError(report_id)
        return report

    def update(self, report_id: str, data: UpdateReport) -> Report:
        existing = self._repository.get_by_id(report_id)
        if existing is None:
            raise ReportNotFoundError(report_id)

        changes = {
            key: value
            for key, value in data.model_dump(exclude_unset=True).items()
            if value is not None
        }
        updated = Report.model_validate({**existing.model_dump(), **changes})
        return self._repository.update(report_id, updated)