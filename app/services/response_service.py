"""Phase 12 response-activity business logic.

Layers: HTTP -> responses router -> validated CreateResponse / UpdateResponse /
ResponseQuery -> ResponseService -> ReportRepository + ResponseRepository +
AuditRepository (all in-memory today, PostgreSQL later).

The service is intentionally thin and deterministic:

- every response is validated against the reports repository (report_id must
  exist), so recorded activities always trace back to a real reported need;
- a response is created once and its identity is preserved across status
  updates - a PATCH never spawns a duplicate record;
- RECORDING IS NOT PROOF: the service never asserts anything about the real
  world; it only records that an activity was (or was not) logged in this
  system;
- an important status change is written to the existing Phase 9 append-only
  audit log (AuditAction.UPDATE_RESPONSE) - nothing new is invented, the
  audit repository is simply reused.
"""

import uuid
from datetime import datetime, timezone

from app.audit.schemas import AuditAction, AuditRecord
from app.models.report import Report
from app.repositories.audit_repository import AuditRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.response_repository import ResponseRepository
from app.response_activity.schemas import (
    CreateResponse,
    ResponseActivity,
    ResponseQuery,
    ResponseStatus,
    UpdateResponse,
)
from app.services.report_service import ReportNotFoundError
from app.utils.datetime_utils import as_utc
from app.utils.strings import contains_ci


class ResponseNotFoundError(Exception):
    """Raised when a response activity with the requested id does not exist."""

    def __init__(self, response_id: str) -> None:
        self.response_id = response_id
        super().__init__(f"Response activity '{response_id}' not found")


class NoResponseChangeError(Exception):
    """Raised when an update attempt changes nothing (e.g. same status)."""

    def __init__(self, response_id: str) -> None:
        self.response_id = response_id
        super().__init__(
            f"Update for response activity '{response_id}' did not change any field"
        )


class ResponseService:
    """Records, retrieves and updates response activities.

    Depends only on repository interfaces, so report, response and audit
    storage can be swapped for a database later without changing this layer.
    """

    def __init__(
        self,
        response_repository: ResponseRepository,
        report_repository: ReportRepository,
        audit_repository: AuditRepository,
    ) -> None:
        self._response_repository = response_repository
        self._report_repository = report_repository
        self._audit_repository = audit_repository

    def create(self, data: CreateResponse) -> ResponseActivity:
        """Validate the referenced report and store a new activity."""
        self._require_report(data.report_id)
        now = datetime.now(timezone.utc)
        response = ResponseActivity(
            response_id=uuid.uuid4().hex,
            report_id=data.report_id,
            need=data.need,
            activity=data.activity.strip(),
            response_status=data.response_status,
            timestamp=as_utc(data.timestamp) if data.timestamp else now,
            location=data.location,
            source=data.source,
            notes=data.notes,
            affected_population=data.affected_population,
        )
        return self._response_repository.create(response)

    def get_by_id(self, response_id: str) -> ResponseActivity:
        """Return one activity, or raise if it does not exist."""
        response = self._response_repository.get_by_id(response_id)
        if response is None:
            raise ResponseNotFoundError(response_id)
        return response

    def list(self, query: ResponseQuery) -> list[ResponseActivity]:
        """Return activities matching every filter, newest first."""
        activities = self._response_repository.get_all()
        activities = [
            a for a in activities if matches_response_activity(a, query)
        ]
        return sorted(
            activities,
            key=lambda a: (as_utc(a.timestamp), a.response_id),
            reverse=True,
        )

    def update(
        self, response_id: str, data: UpdateResponse
    ) -> ResponseActivity:
        """Apply controlled field updates in place, preserving identity.

        When the response status changes, the old/new value is appended to the
        Phase 9 audit log (UPDATE_RESPONSE) with the optional actor/reason so
        the important lifecycle change stays traceable. Other benign edits
        (activity/notes/population) update the activity without a new record.
        """
        existing = self.get_by_id(response_id)

        changes: dict[str, object] = {}
        if data.response_status is not None:
            changes["response_status"] = data.response_status
        if data.activity is not None:
            changes["activity"] = data.activity.strip()
        if data.notes is not None:
            changes["notes"] = data.notes
        if data.affected_population is not None:
            changes["affected_population"] = data.affected_population

        planned = ResponseActivity.model_validate(
            {**existing.model_dump(), **changes}
        )
        if planned == existing:
            raise NoResponseChangeError(response_id)

        stored = self._response_repository.update(response_id, planned)
        if stored is None:
            raise ResponseNotFoundError(response_id)

        if (
            data.response_status is not None
            and data.response_status != existing.response_status
        ):
            self._audit_status_change(
                response=existing,
                old_status=existing.response_status,
                new_status=data.response_status,
                actor_id=data.actor_id,
                reason=data.reason,
            )
        return stored

    # ------------------------------------------------------------------ priv

    def _require_report(self, report_id: str) -> Report:
        report = self._report_repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError(report_id)
        return report

    def _audit_status_change(
        self,
        *,
        response: ResponseActivity,
        old_status: ResponseStatus,
        new_status: ResponseStatus,
        actor_id: str | None,
        reason: str | None,
    ) -> None:
        record = AuditRecord(
            audit_id=uuid.uuid4().hex,
            report_id=response.report_id,
            action=AuditAction.UPDATE_RESPONSE,
            actor_id=actor_id,
            timestamp=datetime.now(timezone.utc),
            reason=reason,
            old_value={"response_status": old_status.value},
            new_value={"response_status": new_status.value},
        )
        self._audit_repository.create(record)


def _matches_time(
    timestamp: datetime,
    start_time: datetime | None,
    end_time: datetime | None,
) -> bool:
    value = as_utc(timestamp)
    if start_time is not None and value < as_utc(start_time):
        return False
    if end_time is not None and value > as_utc(end_time):
        return False
    return True


def matches_response_activity(
    activity: ResponseActivity, query: ResponseQuery
) -> bool:
    """AND-filter a response activity against a ResponseQuery.

    Single implementation shared by the responses list and its map projection
    (which converts its own query to a ResponseQuery), so report_id, need,
    status, source, location and time filters never diverge.
    """
    if query.report_id is not None and activity.report_id != query.report_id:
        return False
    if query.need is not None and activity.need != query.need:
        return False
    if (
        query.response_status is not None
        and activity.response_status != query.response_status
    ):
        return False
    if query.source is not None and not contains_ci(
        activity.source, query.source
    ):
        return False
    if query.location is not None and not contains_ci(
        activity.location, query.location
    ):
        return False
    return _matches_time(activity.timestamp, query.start_time, query.end_time)