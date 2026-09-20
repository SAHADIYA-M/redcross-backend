import uuid
from datetime import datetime, timezone

from app.models.report import Report
from app.repositories.report_repository import ReportRepository
from app.schemas.report import CreateReport, UpdateReport


def _snapshot_extraction(report: Report) -> dict[str, object]:
    """Immutable snapshot of the AI-generated structured interpretation.

    Captured once at creation and never overwritten by verification, so the
    original AI output always stays distinguishable from later human
    corrections. Enum values are serialized to strings for JSON safety.
    """
    return {
        "incident": report.incident,
        "location": report.location,
        "needs": [need.value for need in report.needs],
        "severity": report.severity.value if report.severity else None,
        "affected_population": report.affected_population,
        "vulnerability": list(report.vulnerability),
        "time_sensitivity": report.time_sensitivity,
        "evidence": list(report.evidence),
        "infrastructure_status": (
            report.infrastructure_status.value
            if report.infrastructure_status
            else None
        ),
        "available_needs": [need.value for need in report.available_needs],
    }


from app.utils.datetime_utils import as_utc

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
            timestamp=as_utc(data.timestamp) if data.timestamp else datetime.now(timezone.utc),
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
        stored = Report.model_validate(
            {
                **report.model_dump(),
                "original_extraction": _snapshot_extraction(report),
            }
        )
        created = self._repository.create(stored)
        try:
            from app.core.container import get_fusion_service
            import hashlib
            
            location = created.location or "Unknown Location"
            need = created.needs[0].value if created.needs else "General Request"
            key = f"{location}::{need}"
            cluster_id = f"NEX-{hashlib.md5(key.encode()).hexdigest()[:6].upper()}"
            
            all_reports = self._repository.get_all()
            cluster_reports = []
            for r in all_reports:
                r_location = r.location or "Unknown Location"
                r_need = r.needs[0].value if r.needs else "General Request"
                r_key = f"{r_location}::{r_need}"
                if r_key == key:
                    cluster_reports.append(r)
            
            get_fusion_service().analyze_cluster(cluster_id, cluster_reports)
        except Exception as e:
            import logging
            logging.error(f"Fusion analysis failed: {e}")
            
        return created

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

        # exclude_unset keeps only the fields the client actually sent, so an
        # explicit null is honoured as a request to clear a claim rather than
        # being dropped (a missing claim must never be treated as a fact).
        changes = data.model_dump(exclude_unset=True)
        updated = Report.model_validate({**existing.model_dump(), **changes})
        return self._repository.update(report_id, updated)
