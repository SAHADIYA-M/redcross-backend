"""Human verification workflow backed by the shared report repository.

The AI extracts a structured interpretation; a human reviewer then approves,
edits, rejects, marks uncertain, or requests assessment of it. Every action
creates one verification record and one append-only audit record, and the
original report text/evidence are never modified.

Priority interaction (Phase 8): the backend remains the only authority on
priority scores. After an EDIT the priority is recalculated from the corrected
structured input by reusing the Phase 8 priority service, or is invalidated
(None) when the edited report no longer carries usable priority information.
"""

import uuid
from datetime import datetime, timezone

from app.audit.schemas import AuditAction, AuditRecord
from app.models.report import Report
from app.repositories.audit_repository import AuditRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.verification_repository import VerificationRepository
from app.schemas.priority import PriorityResponse
from app.schemas.report import ReportResponse
from app.schemas.verification import (
    AssessmentRequestResponse,
    RequestAssessmentRequest,
    VerifyRequest,
    VerifyResponse,
)
from app.services.priority_service import PriorityService
from app.services.report_service import ReportNotFoundError
from app.verification.schemas import (
    VerificationAction,
    VerificationRecord,
    VerificationStatus,
)

# Current statuses from which each action is allowed to move a report.
# REQUEST_ASSESSMENT may be submitted from any status (it is a flag, not a
# verdict), which also gives rejected reports a controlled re-review path.
_TRANSITIONS: dict[VerificationAction, frozenset[VerificationStatus]] = {
    VerificationAction.APPROVE: frozenset(
        {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.UNCERTAIN,
            VerificationStatus.ASSESSMENT_REQUESTED,
        }
    ),
    VerificationAction.EDIT: frozenset(
        {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.UNCERTAIN,
            VerificationStatus.ASSESSMENT_REQUESTED,
            VerificationStatus.VERIFIED,
        }
    ),
    VerificationAction.REJECT: frozenset(
        {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.UNCERTAIN,
            VerificationStatus.ASSESSMENT_REQUESTED,
            VerificationStatus.VERIFIED,
        }
    ),
    VerificationAction.MARK_UNCERTAIN: frozenset(
        {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.ASSESSMENT_REQUESTED,
            VerificationStatus.VERIFIED,
            VerificationStatus.UNCERTAIN,
        }
    ),
    VerificationAction.REQUEST_ASSESSMENT: frozenset(VerificationStatus),
}

_TARGET_STATUS: dict[VerificationAction, VerificationStatus] = {
    VerificationAction.APPROVE: VerificationStatus.VERIFIED,
    VerificationAction.EDIT: VerificationStatus.VERIFIED,
    VerificationAction.REJECT: VerificationStatus.REJECTED,
    VerificationAction.MARK_UNCERTAIN: VerificationStatus.UNCERTAIN,
}

# List-typed claims on the domain model: a reviewer clears one by submitting
# null, which normalizes to the empty list the Report model uses for "no
# claim" (never to an invalid null).
_LIST_CLAIM_FIELDS = frozenset({"needs", "vulnerability", "available_needs"})


class InvalidVerificationTransitionError(Exception):
    """Raised when the report's current status forbids the requested action."""

    def __init__(
        self,
        report_id: str,
        action: VerificationAction,
        status: VerificationStatus,
    ) -> None:
        self.report_id = report_id
        self.action = action
        self.status = status
        super().__init__(
            f"Cannot {action.value} report '{report_id}' from status "
            f"{status.value}"
        )


class NoVerificationChangeError(Exception):
    """Raised when an EDIT request would change nothing."""

    def __init__(self, report_id: str) -> None:
        self.report_id = report_id
        super().__init__(
            f"EDIT for report '{report_id}' did not change any field"
        )


class VerificationService:
    """Orchestrates human verification of a report's AI interpretation.

    Depends only on repository interfaces, so the report, verification and
    audit storage can be swapped for a database later without changing this
    layer.

    Rules enforced here:
    - AI output is never verified by the AI; only a human action changes the
      verification status.
    - original report text and evidence are never modified (they are not
      among the editable fields).
    - every action produces one verification record and one audit record.
    - defaults are honoured: a new report starts UNVERIFIED, and a reviewer
      can refuse to choose true/false via MARK_UNCERTAIN.
    """

    def __init__(
        self,
        report_repository: ReportRepository,
        verification_repository: VerificationRepository,
        audit_repository: AuditRepository,
        priority_service: PriorityService | None = None,
    ) -> None:
        self._report_repository = report_repository
        self._verification_repository = verification_repository
        self._audit_repository = audit_repository
        # The Phase 8 service is injected so verification reuses the exact
        # priority instance the rest of the app uses (including its result
        # store, which the PostgreSQL stack wires). The fallback keeps the
        # service constructible for tests without a store.
        self._priority_service = priority_service or PriorityService(
            report_repository
        )

    def verify(self, report_id: str, data: VerifyRequest) -> VerifyResponse:
        """Apply a verification action and return the updated state."""
        report = self._require_report(report_id)
        previous_status = report.verification_status
        new_status = self._target_status(data.action, report_id, previous_status)

        if data.action == VerificationAction.EDIT:
            changes = self._apply_edits(data, report)
            updated = self._store_updated(report_id, changes, new_status)
        else:
            updated = self._store_updated(report_id, {}, new_status)

        record = self._record_action(
            report_id=report_id,
            action=data.action,
            previous_status=previous_status,
            new_status=new_status,
            reviewer_id=data.reviewer_id,
            reason=data.reason,
            changes=changes if data.action == VerificationAction.EDIT else {},
        )
        priority = self._recalculate_priority(data.action, report_id)
        return VerifyResponse(
            report=ReportResponse.model_validate(updated),
            verification=record,
            priority=priority,
        )

    def request_assessment(
        self, report_id: str, data: RequestAssessmentRequest
    ) -> AssessmentRequestResponse:
        """Flag a report for further human assessment.

        Marks the report ASSESSMENT_REQUESTED. This is a request for further
        assessment, never a verification result: the report is not treated as
        verified.
        """
        report = self._require_report(report_id)
        previous_status = report.verification_status
        new_status = VerificationStatus.ASSESSMENT_REQUESTED
        updated = self._store_updated(report_id, {}, new_status)
        record = self._record_action(
            report_id=report_id,
            action=VerificationAction.REQUEST_ASSESSMENT,
            previous_status=previous_status,
            new_status=new_status,
            reviewer_id=data.reviewer_id,
            reason=data.reason,
            changes={},
        )
        return AssessmentRequestResponse(
            report=ReportResponse.model_validate(updated),
            verification=record,
        )

    def list_verifications(
        self,
        *,
        report_id: str | None = None,
        status: VerificationStatus | None = None,
        action: VerificationAction | None = None,
    ) -> list[VerificationRecord]:
        """Return verification records, newest first, with optional filters."""
        records = self._verification_repository.get_all()
        if report_id is not None:
            records = [r for r in records if r.report_id == report_id]
        if status is not None:
            records = [r for r in records if r.new_status == status]
        if action is not None:
            records = [r for r in records if r.action == action]
        return sorted(records, key=lambda r: r.timestamp, reverse=True)

    # ------------------------------------------------------------------ priv

    def _require_report(self, report_id: str) -> Report:
        report = self._report_repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError(report_id)
        return report

    @staticmethod
    def _target_status(
        action: VerificationAction,
        report_id: str,
        current: VerificationStatus,
    ) -> VerificationStatus:
        allowed = _TRANSITIONS[action]
        if current not in allowed:
            raise InvalidVerificationTransitionError(report_id, action, current)
        return _TARGET_STATUS[action]

    @staticmethod
    def _apply_edits(data: VerifyRequest, report: Report) -> dict[str, dict[str, object]]:
        """Compute field-level old/new values for an EDIT.

        Only fields that actually change are recorded, so an EDIT that changes
        nothing is rejected instead of producing an empty audit entry.
        """
        edits = data.edits.model_dump(exclude_unset=True) if data.edits else {}
        changes: dict[str, dict[str, object]] = {}
        for field, new_value in edits.items():
            # List-typed claims are stored as empty lists, never null: a
            # reviewer clearing a list claim (needs/vulnerability/
            # available_needs) submits null, which the domain model renders as
            # "no claim", i.e. an empty list. Applying null verbatim would
            # fail Report validation and surface a 500 instead of a clean edit.
            if new_value is None and field in _LIST_CLAIM_FIELDS:
                new_value = []
            old_value = getattr(report, field)
            if old_value != new_value:
                changes[field] = {"old": old_value, "new": new_value}
        if not changes:
            raise NoVerificationChangeError(report.id)
        return changes

    def _store_updated(
        self,
        report_id: str,
        changes: dict[str, dict[str, object]],
        new_status: VerificationStatus,
    ) -> Report:
        report = self._require_report(report_id)
        data = report.model_dump()
        for field, change in changes.items():
            data[field] = change["new"]
        data["verification_status"] = new_status
        updated = Report.model_validate(data)
        stored = self._report_repository.update(report_id, updated)
        if stored is None:
            raise ReportNotFoundError(report_id)
        return stored

    def _record_action(
        self,
        *,
        report_id: str,
        action: VerificationAction,
        previous_status: VerificationStatus | None,
        new_status: VerificationStatus | None,
        reviewer_id: str | None,
        reason: str | None,
        changes: dict[str, dict[str, object]],
    ) -> VerificationRecord:
        now = datetime.now(timezone.utc)
        record = VerificationRecord(
            verification_id=uuid.uuid4().hex,
            report_id=report_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reviewer_id=reviewer_id,
            reason=reason,
            timestamp=now,
            changes=changes,
        )
        self._verification_repository.create(record)

        if changes:
            old_value = {field: change["old"] for field, change in changes.items()}
            new_value = {field: change["new"] for field, change in changes.items()}
        else:
            old_value = (
                {"verification_status": previous_status.value}
                if previous_status is not None
                else {}
            )
            new_value = (
                {"verification_status": new_status.value}
                if new_status is not None
                else {}
            )

        audit = AuditRecord(
            audit_id=uuid.uuid4().hex,
            report_id=report_id,
            action=AuditAction(action.value),
            actor_id=reviewer_id,
            timestamp=now,
            reason=reason,
            old_value=old_value,
            new_value=new_value,
        )
        self._audit_repository.create(audit)
        return record

    def _recalculate_priority(
        self, action: VerificationAction, report_id: str
    ) -> PriorityResponse | None:
        """Reuse the Phase 8 priority service after an EDIT.

        A reviewer can never set a score directly; the backend derives it. When
        the edited report no longer carries usable priority input, the result
        is invalidated (None) instead of forcing a value.

        The recalculation runs through the shared ``PriorityService`` instance,
        so the recomputed result is persisted to the same result store the
        priority API and report-update path use (identity, not a fresh
        store-less copy).
        """
        if action != VerificationAction.EDIT:
            return None
        return self._priority_service.recalculate_for_report(report_id)