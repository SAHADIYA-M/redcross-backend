import hashlib
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from app.audit.schemas import AuditAction, AuditRecord
from app.core.database import DatabaseIntegrityError, DatabaseUnavailableError
from app.models.report import Report
from app.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.repositories.report_repository import ReportRepository
from app.schemas.report import CreateReport, UpdateReport

if TYPE_CHECKING:
    from app.services.priority_service import PriorityService

logger = logging.getLogger(__name__)


# Editable report fields that feed the backend priority calculation. A change
# to any of these makes the stored priority result stale and must trigger a
# backend recalculation (or invalidation); other fields do not touch priority.
_PRIORITY_RELEVANT_FIELDS = frozenset(
    {
        "severity",
        "affected_population",
        "vulnerability",
        "time_sensitivity",
        "evidence",
    }
)


def _json_safe(value: object) -> object:
    """Coerce a report value into a JSON-serialisable audit primitive."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _effective_changes(
    existing: Report, changes: dict[str, object]
) -> dict[str, dict[str, object]]:
    """Return only the fields whose submitted value differs from the stored one."""
    result: dict[str, dict[str, object]] = {}
    for field, new_value in changes.items():
        old_value = getattr(existing, field)
        if old_value != new_value:
            result[field] = {"old": old_value, "new": new_value}
    return result


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

    def __init__(
        self,
        repository: ReportRepository,
        audit_repository: AuditRepository | None = None,
        priority_service: "PriorityService | None" = None,
    ) -> None:
        self._repository = repository
        self._audit_repository = audit_repository
        self._priority_service = priority_service

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
        self._run_fusion_analysis(created)
        return created

    def _run_fusion_analysis(self, report: Report) -> None:
        """Best-effort duplicate/conflict candidate analysis after persist.

        Runs strictly after the report has been persisted, so a failure here
        never loses data. Only reports sharing the report's fusion cluster
        (``get_cluster_candidates``) are loaded, never the whole table.

        Candidate generation is a background-quality side channel: the report
        is already durably stored, so a failure to write candidates must NOT
        turn a successful intake into a 503/409 response. Declaring a persisted
        report "failed" invites the client to resubmit and create a duplicate,
        which is the exact data-integrity hazard fusion exists to prevent.
        Expected (recoverable) failures - the fusion store is down or rejects
        the write - are logged as warnings; unexpected failures are logged as
        errors. Neither is silently dropped, and neither fails the create.
        """
        try:
            from app.core.container import get_fusion_service

            cluster_id = (
                "NEX-"
                + hashlib.md5(
                    f"{report.cluster_location}::{report.cluster_need}".encode()
                ).hexdigest()[:6].upper()
            )
            cluster_reports = self._repository.get_cluster_candidates(
                report.cluster_location, report.cluster_need
            )
            get_fusion_service().analyze_cluster(cluster_id, cluster_reports)
        except (DatabaseUnavailableError, DatabaseIntegrityError) as exc:
            logger.warning(
                "Fusion candidate analysis did not complete for report %s: %s",
                report.id,
                exc,
            )
        except Exception:
            logger.error(
                "Unexpected failure during fusion analysis for report %s",
                report.id,
                exc_info=True,
            )

    def get_all(self) -> list[Report]:
        return self._repository.get_all()

    def get_by_id(self, report_id: str) -> Report:
        report = self._repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError(report_id)
        return report

    def update(
        self,
        report_id: str,
        data: UpdateReport,
        *,
        actor: User | None = None,
    ) -> Report:
        """Apply an authorized partial update and record it in the audit log.

        ``actor`` is the authenticated caller identity supplied by the API
        layer; it is never read from the request body, so a client cannot
        forge who performed the change. The original evidence is never
        overwritten, every effective change is audited, and a change to any
        priority-relevant field triggers a backend priority recalculation.
        """
        existing = self._repository.get_by_id(report_id)
        if existing is None:
            raise ReportNotFoundError(report_id)

        # exclude_unset keeps only the fields the client actually sent, so an
        # explicit null is honoured as a request to clear a claim rather than
        # being dropped (a missing claim must never be treated as a fact).
        changes = data.model_dump(exclude_unset=True)
        # Defence in depth: even if schema validation were bypassed, the
        # original evidence text can never be overwritten.
        changes.pop("original_text", None)

        updated = Report.model_validate({**existing.model_dump(), **changes})
        stored = self._repository.update(report_id, updated)
        if stored is None:
            raise ReportNotFoundError(report_id)

        effective = _effective_changes(existing, changes)
        if effective:
            self._record_update_audit(report_id, effective, actor)
            if set(effective) & _PRIORITY_RELEVANT_FIELDS:
                self._refresh_priority(report_id)
        return stored

    def _record_update_audit(
        self,
        report_id: str,
        effective: dict[str, dict[str, object]],
        actor: User | None,
    ) -> None:
        """Append one audit record describing exactly what changed.

        Old/new values carry only the changed fields, and the actor is the
        authenticated identity passed in by the API layer (never a body
        field). No audit is written when there is nothing to record.
        """
        if self._audit_repository is None:
            return
        old_value = {
            field: _json_safe(change["old"]) for field, change in effective.items()
        }
        new_value = {
            field: _json_safe(change["new"]) for field, change in effective.items()
        }
        self._audit_repository.create(
            AuditRecord(
                audit_id=uuid.uuid4().hex,
                report_id=report_id,
                action=AuditAction.UPDATE_REPORT,
                actor_id=actor.user_id if actor is not None else None,
                timestamp=datetime.now(timezone.utc),
                old_value=old_value,
                new_value=new_value,
            )
        )

    def _refresh_priority(self, report_id: str) -> None:
        """Recompute or invalidate the stored priority via the Phase 8 service.

        The backend remains the sole authority: no client-supplied score is
        ever consulted. Failures here never undo the committed report edit.
        """
        if self._priority_service is None:
            return
        try:
            self._priority_service.recalculate_for_report(report_id)
        except Exception as exc:  # pragma: no cover - defensive safety net
            import logging

            logging.error("Priority recalculation after report update failed: %s", exc)
