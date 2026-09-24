"""PostgreSQL repositories (SQLAlchemy 2.x) implementing the app's repository
interfaces.

Every repository keeps the same interface contract as its in-memory sibling,
so the API/service layers are unchanged when storage is swapped. Concrete
notes:

- ``full_name`` is written as an empty string when unset because the team's
  ``users`` table declares ``full_name TEXT NOT NULL``; it is read back as
  ``None`` so the API keeps "no name provided" semantics.
- reports keep their original text immutable through the verification
  workflow (no verification write touches it), exactly as the domain model
  requires.
- uncertain locations are stored as NULL coordinates / UNCERTAIN status; they
  are never coerced to 0,0.
- audit logs are append-only: only ``create``/``get_all`` exist.
"""

from datetime import datetime, timezone

from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.schemas import AuditAction, AuditRecord
from app.core.database import (
    DatabaseIntegrityError,
    DatabaseUnavailableError,
    translate_sqlalchemy_error,
)
from app.models.db_models import (
    AuditLogRow,
    FusionCandidateRow,
    PriorityResultRow,
    ReportNeedRow,
    ReportRow,
    ResponseActivityRow,
    UserRow,
    VerificationRecordRow,
)
from app.models.fusion import (
    FusionCandidate,
    FusionResolution,
    FusionStatus,
    FusionType,
)
from app.models.report import (
    DEFAULT_CLUSTER_LOCATION,
    DEFAULT_CLUSTER_NEED,
    Report,
    ReportStatus,
)
from app.models.user import User, UserRole
from app.repositories.audit_repository import AuditRepository
from app.repositories.fusion_repository import FusionRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.response_repository import ResponseRepository
from app.repositories.user_repository import UserRepository
from app.repositories.verification_repository import VerificationRepository
from app.response_activity.schemas import ResponseActivity, ResponseStatus
from app.services.auth_service import DuplicateUserError
from app.utils.datetime_utils import as_utc
from app.verification.schemas import (
    VerificationAction,
    VerificationRecord,
    VerificationStatus,
)
from app.ai.schemas import NeedCategory, SeverityLevel
from app.conflicts.schemas import InfrastructureStatus
from app.location.schemas import LocationStatus


def _run(session_factory, fn):
    """Run ``fn(session)`` with commit-on-success / rollback-on-failure."""
    session = session_factory()
    try:
        result = fn(session)
        session.commit()
        return result
    except DatabaseUnavailableError:
        session.rollback()
        raise
    except DatabaseIntegrityError:
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise translate_sqlalchemy_error(exc) from exc
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class PostgresUserRepository(UserRepository):
    """SQLAlchemy implementation of :class:`UserRepository` (users table)."""

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def create_user(self, user: User) -> User:
        def op(session):
            row = UserRow(
                user_id=user.user_id,
                username=user.username,
                password_hash=user.password_hash,
                full_name=user.full_name or "",
                role=user.role.value if isinstance(user.role, UserRole) else str(user.role),
                is_active=user.is_active,
                created_at=as_utc(user.created_at),
            )
            session.add(row)
            return user

        try:
            return _run(self._factory, op)
        except DatabaseIntegrityError as exc:
            # The unique index on lower(username) (team migration 001) makes a
            # concurrent duplicate registration surface here as a 409 the same
            # way the in-memory pre-check does.
            raise DuplicateUserError(user.username) from exc

    def get_by_id(self, user_id: str) -> User | None:
        def op(session):
            row = session.get(UserRow, user_id)
            return _user_from_row(row) if row else None

        return _run(self._factory, op)

    def get_by_username(self, username: str) -> User | None:
        def op(session):
            row = session.scalar(
                select(UserRow).where(
                    func.lower(UserRow.username) == username.casefold()
                )
            )
            return _user_from_row(row) if row else None

        return _run(self._factory, op)

    def list_users(self) -> list[User]:
        def op(session):
            rows = session.scalars(
                select(UserRow).order_by(UserRow.created_at)
            ).all()
            return [_user_from_row(row) for row in rows]

        return _run(self._factory, op)

    def update_user(self, user: User) -> User | None:
        def op(session):
            row = session.get(UserRow, user.user_id)
            if row is None:
                return None
            row.username = user.username
            row.password_hash = user.password_hash
            row.full_name = user.full_name or ""
            row.role = (
                user.role.value if isinstance(user.role, UserRole) else str(user.role)
            )
            row.is_active = user.is_active
            return user

        try:
            return _run(self._factory, op)
        except DatabaseIntegrityError as exc:
            raise DuplicateUserError(user.username) from exc


def _user_from_row(row: UserRow) -> User:
    return User(
        user_id=row.user_id,
        username=row.username,
        password_hash=row.password_hash,
        full_name=row.full_name or None,
        role=UserRole(row.role),
        is_active=row.is_active,
        created_at=as_utc(row.created_at),
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class PostgresReportRepository(ReportRepository):
    """SQLAlchemy implementation of :class:`ReportRepository` (reports table).

    The original report text is stored verbatim and no verification/priority
    write touches it. Locations preserve their explicit status; uncertain
    locations are stored as NULL coordinates combined with UNCERTAIN (never
    0,0).
    """

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def create(self, report: Report) -> Report:
        def op(session):
            row = _row_from_report(report)
            session.add(row)
            # Persist the parent row first: the report_need_records child rows
            # carry an immediate PostgreSQL foreign key to reports, and the
            # unit of work queues both row sets in one flush without mapping
            # relationships, so children must not be emitted before the parent.
            session.flush()
            _write_needs(session, report.id, report.needs)
            return report

        return _run(self._factory, op)

    def get_by_id(self, report_id: str) -> Report | None:
        def op(session):
            row = session.get(ReportRow, report_id)
            if row is None:
                return None
            needs = _read_needs(session, [report_id])[report_id]
            return _report_from_row(row, needs)

        return _run(self._factory, op)

    def get_all(self) -> list[Report]:
        def op(session):
            rows = session.scalars(
                select(ReportRow).order_by(ReportRow.created_at)
            ).all()
            ids = [r.report_id for r in rows]
            all_needs = _read_needs(session, ids)
            return [_report_from_row(row, all_needs.get(row.report_id, [])) for row in rows]

        return _run(self._factory, op)

    def update(self, report_id: str, report: Report) -> Report | None:
        def op(session):
            row = session.get(ReportRow, report_id)
            if row is None:
                return None
            updated = _row_from_report(report)
            for field in (
                "original_text",
                "reporter",
                "timestamp",
                "location",
                "incident",
                "evidence",
                "status",
                "source",
                "location_status",
                "severity",
                "affected_population",
                "infrastructure_status",
                "available_needs",
                "vulnerability",
                "time_sensitivity",
                "verification_status",
                "original_extraction",
            ):
                setattr(row, field, getattr(updated, field))
            session.execute(
                delete(ReportNeedRow).where(ReportNeedRow.report_id == report_id)
            )
            _write_needs(session, report_id, report.needs)
            return report

        return _run(self._factory, op)

    def search_reports(self, query) -> list[Report]:
        """Filter reports with database-side (non-priority, non-bbox) query.

        Mirrors the SearchService._matches rule set (text, needs, verification,
        status, location text, location status, incident, source, time range)
        without loading the whole table into Python. Bounding-box and priority
        filters are intentionally left to the service layer, which has the
        geocoder and the Phase 8 calculator.
        """
        if query is None or query.has_bounding_box:
            raise NotImplementedError
        has_filters = any(
            param is not None
            for param in (
                query.q,
                query.need,
                query.verification_status,
                query.status,
                query.location,
                query.location_status,
                query.incident,
                query.source,
                query.start_time,
                query.end_time,
            )
        )
        if not has_filters:
            # No non-priority filter to push down: get_all() is the efficient
            # path and keeps map/report consumers on the same data.
            raise NotImplementedError

        def op(session):
            stmt = select(ReportRow).order_by(ReportRow.created_at)
            if query.q:
                stmt = stmt.where(
                    ReportRow.original_text.ilike(
                        _like_contains(query.q), escape=_ILIKE_ESCAPE
                    )
                )
            if query.need:
                need_values = [need.value for need in query.need]
                sub = (
                    select(1)
                    .where(ReportNeedRow.report_id == ReportRow.report_id)
                    .where(ReportNeedRow.need.in_(need_values))
                )
                stmt = stmt.where(exists(sub))
            if query.verification_status is not None:
                stmt = stmt.where(
                    ReportRow.verification_status == query.verification_status.value
                )
            if query.status is not None:
                stmt = stmt.where(ReportRow.status == query.status.value)
            if query.location is not None:
                stmt = stmt.where(
                    ReportRow.location.ilike(
                        _like_contains(query.location), escape=_ILIKE_ESCAPE
                    )
                )
            if query.location_status is not None:
                stmt = stmt.where(
                    ReportRow.location_status == query.location_status.value
                )
            if query.incident is not None:
                stmt = stmt.where(
                    ReportRow.incident.ilike(
                        _like_contains(query.incident), escape=_ILIKE_ESCAPE
                    )
                )
            if query.source is not None:
                stmt = stmt.where(
                    ReportRow.source.ilike(
                        _like_contains(query.source), escape=_ILIKE_ESCAPE
                    )
                )
            if query.start_time is not None:
                stmt = stmt.where(ReportRow.timestamp >= as_utc(query.start_time))
            if query.end_time is not None:
                stmt = stmt.where(ReportRow.timestamp <= as_utc(query.end_time))
            rows = session.scalars(stmt).all()
            ids = [r.report_id for r in rows]
            all_needs = _read_needs(session, ids)
            return [
                _report_from_row(row, all_needs.get(row.report_id, []))
                for row in rows
            ]

        return _run(self._factory, op)

    def get_cluster_candidates(self, location: str, need: str) -> list[Report]:
        """Fetch only the reports in the requested fusion cluster (no full scan).

        Matches on the normalized cluster key: ``coalesce(nullif(location,
        ''), 'Unknown Location')`` and the first need (``ReportNeedRow.position
        == 0``) or the no-need fallback — the exact semantics of
        :attr:`Report.cluster_location` / :attr:`Report.cluster_need`. The
        nullif keeps parity with the in-memory store: a report carrying an
        empty-string location clusters under ``Unknown Location`` just like a
        NULL one, instead of silently dropping out of its own cluster.
        """
        def op(session):
            stmt = select(ReportRow).where(
                func.coalesce(
                    func.nullif(ReportRow.location, ""), DEFAULT_CLUSTER_LOCATION
                )
                == location
            )
            if need == DEFAULT_CLUSTER_NEED:
                stmt = stmt.where(
                    ~exists(
                        select(1).where(
                            ReportNeedRow.report_id == ReportRow.report_id
                        )
                    )
                )
            else:
                stmt = stmt.where(
                    exists(
                        select(1)
                        .where(
                            ReportNeedRow.report_id == ReportRow.report_id
                        )
                        .where(ReportNeedRow.position == 0)
                        .where(ReportNeedRow.need == need)
                    )
                )
            rows = session.scalars(stmt).all()
            ids = [row.report_id for row in rows]
            all_needs = _read_needs(session, ids)
            return [
                _report_from_row(row, all_needs.get(row.report_id, []))
                for row in rows
            ]

        return _run(self._factory, op)


def _like_contains(value: str) -> str:
    """Escape a needle for ``ILIKE '%...%'`` so user text matches literally."""
    escaped = (
        value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    )
    return f"%{escaped}%"


# One escape character for every ILIKE call. PostgreSQL defaults to backslash,
# but SQLite does not; passing the ESCAPE explicitly keeps both backends
# faithful so ``%`` and ``_`` in user text are always literal.
_ILIKE_ESCAPE = "\\"


def _write_needs(session, report_id: str, needs: list[NeedCategory]) -> None:
    seen: set[str] = set()
    position = 0
    for need in needs:
        value = need.value if isinstance(need, NeedCategory) else str(need)
        if value in seen:
            continue
        seen.add(value)
        session.add(
            ReportNeedRow(report_id=report_id, need=value, position=position)
        )
        position += 1


def _read_needs(session, report_ids: list[str]) -> dict[str, list[NeedCategory]]:
    if not report_ids:
        return {}
    rows = session.scalars(
        select(ReportNeedRow)
        .where(ReportNeedRow.report_id.in_(report_ids))
        .order_by(ReportNeedRow.report_id, ReportNeedRow.position)
    ).all()
    result: dict[str, list[NeedCategory]] = {rid: [] for rid in report_ids}
    for row in rows:
        result.setdefault(row.report_id, []).append(NeedCategory(row.need))
    return result


def _row_from_report(report: Report) -> ReportRow:
    return ReportRow(
        report_id=report.id,
        original_text=report.original_text,
        reporter=report.reporter,
        timestamp=as_utc(report.timestamp),
        location=report.location,
        incident=report.incident,
        evidence=list(report.evidence),
        status=report.status.value if isinstance(report.status, ReportStatus) else str(report.status),
        source=report.source,
        location_status=(
            report.location_status.value
            if report.location_status is not None
            else None
        ),
        severity=report.severity.value if report.severity else None,
        affected_population=report.affected_population,
        infrastructure_status=(
            report.infrastructure_status.value
            if report.infrastructure_status
            else None
        ),
        available_needs=(
            [n.value if isinstance(n, NeedCategory) else str(n) for n in report.available_needs]
        ),
        vulnerability=list(report.vulnerability),
        time_sensitivity=report.time_sensitivity,
        verification_status=(
            report.verification_status.value
            if hasattr(report.verification_status, "value")
            else str(report.verification_status)
        ),
        original_extraction=dict(report.original_extraction),
        created_at=datetime.now(timezone.utc),
    )


def _report_from_row(row: ReportRow, needs: list[NeedCategory]) -> Report:
    return Report(
        id=row.report_id,
        original_text=row.original_text,
        reporter=row.reporter,
        timestamp=as_utc(row.timestamp),
        location=row.location,
        incident=row.incident,
        evidence=list(row.evidence or []),
        status=ReportStatus(row.status),
        source=row.source,
        needs=needs,
        location_status=(
            LocationStatus(row.location_status) if row.location_status else None
        ),
        severity=SeverityLevel(row.severity) if row.severity else None,
        affected_population=row.affected_population,
        infrastructure_status=(
            InfrastructureStatus(row.infrastructure_status)
            if row.infrastructure_status
            else None
        ),
        available_needs=[
            NeedCategory(n) for n in (row.available_needs or [])
        ],
        vulnerability=list(row.vulnerability or []),
        time_sensitivity=row.time_sensitivity,
        verification_status=VerificationStatus(row.verification_status),
        original_extraction=dict(row.original_extraction or {}),
    )


# ---------------------------------------------------------------------------
# Verification records
# ---------------------------------------------------------------------------


class PostgresVerificationRepository(VerificationRepository):
    """SQLAlchemy implementation of :class:`VerificationRepository`."""

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def create(self, record: VerificationRecord) -> VerificationRecord:
        def op(session):
            session.add(
                VerificationRecordRow(
                    verification_id=record.verification_id,
                    report_id=record.report_id,
                    action=record.action.value,
                    previous_status=(
                        record.previous_status.value
                        if record.previous_status is not None
                        else None
                    ),
                    new_status=(
                        record.new_status.value if record.new_status is not None else None
                    ),
                    reviewer_id=record.reviewer_id,
                    reason=record.reason,
                    timestamp=as_utc(record.timestamp),
                    changes=dict(record.changes),
                )
            )
            return record

        return _run(self._factory, op)

    def get_all(self) -> list[VerificationRecord]:
        def op(session):
            rows = session.scalars(
                select(VerificationRecordRow).order_by(
                    VerificationRecordRow.timestamp
                )
            ).all()
            return [_verification_from_row(row) for row in rows]

        return _run(self._factory, op)


def _verification_from_row(row: VerificationRecordRow) -> VerificationRecord:
    return VerificationRecord(
        verification_id=row.verification_id,
        report_id=row.report_id,
        action=VerificationAction(row.action),
        previous_status=VerificationStatus(row.previous_status) if row.previous_status else None,
        new_status=VerificationStatus(row.new_status) if row.new_status else None,
        reviewer_id=row.reviewer_id,
        reason=row.reason,
        timestamp=as_utc(row.timestamp),
        changes=dict(row.changes or {}),
    )


# ---------------------------------------------------------------------------
# Audit log (append-only)
# ---------------------------------------------------------------------------


class PostgresAuditRepository(AuditRepository):
    """SQLAlchemy implementation of :class:`AuditRepository`.

    Only ``create`` and ``get_all`` exist — there is no update/delete path, so
    the append-only property holds at the interface level, the same as the
    in-memory implementation.
    """

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def create(self, record: AuditRecord) -> AuditRecord:
        def op(session):
            session.add(
                AuditLogRow(
                    audit_id=record.audit_id,
                    report_id=record.report_id,
                    action=record.action.value,
                    actor_id=record.actor_id,
                    timestamp=as_utc(record.timestamp),
                    reason=record.reason,
                    old_value=dict(record.old_value),
                    new_value=dict(record.new_value),
                )
            )
            return record

        return _run(self._factory, op)

    def get_all(self) -> list[AuditRecord]:
        def op(session):
            rows = session.scalars(
                select(AuditLogRow).order_by(AuditLogRow.timestamp)
            ).all()
            return [_audit_from_row(row) for row in rows]

        return _run(self._factory, op)


def _audit_from_row(row: AuditLogRow) -> AuditRecord:
    return AuditRecord(
        audit_id=row.audit_id,
        report_id=row.report_id,
        action=AuditAction(row.action),
        actor_id=row.actor_id,
        timestamp=as_utc(row.timestamp),
        reason=row.reason,
        old_value=dict(row.old_value or {}),
        new_value=dict(row.new_value or {}),
    )


# ---------------------------------------------------------------------------
# Response activities
# ---------------------------------------------------------------------------


class PostgresResponseRepository(ResponseRepository):
    """SQLAlchemy implementation of :class:`ResponseRepository`."""

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def create(self, response: ResponseActivity) -> ResponseActivity:
        def op(session):
            session.add(_response_row(response))
            return response

        return _run(self._factory, op)

    def get_by_id(self, response_id: str) -> ResponseActivity | None:
        def op(session):
            row = session.get(ResponseActivityRow, response_id)
            return _response_from_row(row) if row else None

        return _run(self._factory, op)

    def get_all(self) -> list[ResponseActivity]:
        def op(session):
            rows = session.scalars(
                select(ResponseActivityRow).order_by(ResponseActivityRow.timestamp)
            ).all()
            return [_response_from_row(row) for row in rows]

        return _run(self._factory, op)

    def update(
        self, response_id: str, response: ResponseActivity
    ) -> ResponseActivity | None:
        def op(session):
            row = session.get(ResponseActivityRow, response_id)
            if row is None:
                return None
            updated = _response_row(response)
            row.report_id = updated.report_id
            row.need = updated.need
            row.activity = updated.activity
            row.response_status = updated.response_status
            row.timestamp = updated.timestamp
            row.location = updated.location
            row.source = updated.source
            row.notes = updated.notes
            row.affected_population = updated.affected_population
            return response

        return _run(self._factory, op)


def _response_row(response: ResponseActivity) -> ResponseActivityRow:
    return ResponseActivityRow(
        response_id=response.response_id,
        report_id=response.report_id,
        need=response.need.value if response.need is not None else None,
        activity=response.activity,
        response_status=response.response_status.value,
        timestamp=as_utc(response.timestamp),
        location=response.location,
        source=response.source,
        notes=response.notes,
        affected_population=response.affected_population,
    )


def _response_from_row(row: ResponseActivityRow) -> ResponseActivity:
    return ResponseActivity(
        response_id=row.response_id,
        report_id=row.report_id,
        need=NeedCategory(row.need) if row.need is not None else None,
        activity=row.activity,
        response_status=ResponseStatus(row.response_status),
        timestamp=as_utc(row.timestamp),
        location=row.location,
        source=row.source,
        notes=row.notes,
        affected_population=row.affected_population,
    )


# ---------------------------------------------------------------------------
# Fusion candidates (duplicates / conflicts)
# ---------------------------------------------------------------------------


class PostgresFusionRepository(FusionRepository):
    """SQLAlchemy implementation of :class:`FusionRepository`.

    Backs the reviewable duplicate/conflict queue: candidates are persisted in
    full and are never auto-merged or auto-deleted by storage.
    """

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def get_pending(self) -> list[FusionCandidate]:
        def op(session):
            rows = session.scalars(
                select(FusionCandidateRow).where(
                    FusionCandidateRow.status == FusionStatus.PENDING.value
                )
            ).all()
            return [_fusion_from_row(row) for row in rows]

        return _run(self._factory, op)

    def get_by_id(self, candidate_id: str) -> FusionCandidate | None:
        def op(session):
            row = session.get(FusionCandidateRow, candidate_id)
            return _fusion_from_row(row) if row else None

        return _run(self._factory, op)

    def save(self, candidate: FusionCandidate) -> None:
        def op(session):
            session.merge(_fusion_row(candidate))

        _run(self._factory, op)

    def get_by_cluster(self, cluster_id: str) -> list[FusionCandidate]:
        def op(session):
            rows = session.scalars(
                select(FusionCandidateRow).where(
                    FusionCandidateRow.cluster_id == cluster_id
                )
            ).all()
            return [_fusion_from_row(row) for row in rows]

        return _run(self._factory, op)

    def get_all(self) -> list[FusionCandidate]:
        def op(session):
            rows = session.scalars(
                select(FusionCandidateRow).order_by(FusionCandidateRow.created_at)
            ).all()
            return [_fusion_from_row(row) for row in rows]

        return _run(self._factory, op)


def _fusion_row(candidate: FusionCandidate) -> FusionCandidateRow:
    return FusionCandidateRow(
        id=candidate.id,
        type=candidate.type.value,
        report_ids=list(candidate.report_ids),
        cluster_id=candidate.cluster_id,
        reason=candidate.reason,
        similarity=candidate.similarity,
        status=candidate.status.value,
        resolution=candidate.resolution.value if candidate.resolution else None,
        created_at=candidate.created_at,
        reviewed_at=candidate.reviewed_at,
        reviewed_by=candidate.reviewed_by,
    )


def _fusion_from_row(row: FusionCandidateRow) -> FusionCandidate:
    return FusionCandidate(
        id=row.id,
        type=FusionType(row.type),
        report_ids=list(row.report_ids or []),
        cluster_id=row.cluster_id,
        reason=row.reason,
        similarity=row.similarity,
        status=FusionStatus(row.status),
        resolution=FusionResolution(row.resolution) if row.resolution else None,
        created_at=as_utc(row.created_at),
        reviewed_at=as_utc(row.reviewed_at) if row.reviewed_at else None,
        reviewed_by=row.reviewed_by,
    )


# ---------------------------------------------------------------------------
# Priority results (backend-computed, client-proof)
# ---------------------------------------------------------------------------


class PostgresPriorityResultRepository:
    """Persists Phase 8 priority results per report.

    Values always come from the backend calculation; there is no method a
    client could use to write arbitrary scores.
    """

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def save(self, result) -> None:
        def op(session):
            row = PriorityResultRow(
                report_id=result.report_id,
                severity_score=result.severity_score,
                affected_population_score=result.affected_population_score,
                vulnerability_score=result.vulnerability_score,
                time_sensitivity_score=result.time_sensitivity_score,
                evidence_verification_score=result.evidence_verification_score,
                final_score=result.final_score,
                priority_level=result.priority_level.value,
                calculation_version=result.calculation_version,
                calculated_at=result.calculated_at,
            )
            session.merge(row)

        _run(self._factory, op)

    def get_by_report(self, report_id: str):
        def op(session):
            from app.schemas.priority import PriorityResponse
            from app.priority.schemas import PriorityLevel

            row = session.get(PriorityResultRow, report_id)
            if row is None:
                return None
            return PriorityResponse(
                report_id=row.report_id,
                severity_score=row.severity_score,
                affected_population_score=row.affected_population_score,
                vulnerability_score=row.vulnerability_score,
                time_sensitivity_score=row.time_sensitivity_score,
                evidence_verification_score=row.evidence_verification_score,
                final_score=row.final_score,
                priority_level=PriorityLevel(row.priority_level),
                calculation_version=row.calculation_version,
                calculated_at=row.calculated_at,
            )

        return _run(self._factory, op)

    def delete_by_report(self, report_id: str) -> None:
        """Remove the stored result for a report that lost its priority input.

        Invalidation, not a mutation: no replacement value is fabricated. Only
        the backend calls this (after a report edit); there is no route a
        client could use to delete or set a score.
        """
        def op(session):
            session.execute(
                delete(PriorityResultRow).where(
                    PriorityResultRow.report_id == report_id
                )
            )

        _run(self._factory, op)


__all__ = [
    "PostgresUserRepository",
    "PostgresReportRepository",
    "PostgresVerificationRepository",
    "PostgresAuditRepository",
    "PostgresResponseRepository",
    "PostgresFusionRepository",
    "PostgresPriorityResultRepository",
]