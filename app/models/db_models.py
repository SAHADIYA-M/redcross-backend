"""SQLAlchemy ORM models mapping the application's domain entities to tables.

Explicit table names are used throughout. Names are chosen to NOT collide
with the existing team schema (schema_v2.sql): the only table shared with the
older design is ``users`` (created by ``database/migrations/001_users.sql``);
everything else is a new, additive ``Phase 15`` table. All tables are created
idempotently (CREATE TABLE IF NOT EXISTS via the migration script) and never
drop or alter existing tables.

Column types are PostgreSQL-compatible; list/dict fields use JSON so the same
mappings are testable against SQLite in the offline suite.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def _timestamptz() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False)


class UserRow(Base):
    """Application users (maps the team's ``users`` table from 001_users.sql).

    Column-for-column it matches the existing migration:
    user_id/username/password_hash/full_name/role/is_active/created_at. The
    case-insensitive username uniqueness is backed by the same functional
    index the team already created (``idx_users_username_lower`` on
    ``lower(username)``); when the table does not exist yet, ``create_all``
    creates it with the identical index.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index(
            "idx_users_username_lower",
            text("lower(username)"),
            unique=True,
        ),
    )

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _timestamptz()


class ReportRow(Base):
    """A humanitarian report with the full app-domain representation.

    The original report text (``original_text``) is immutable by design: the
    verification workflow never edits it, and no repository method overwrites
    it. AI-derived claims live in dedicated columns, and the ``original_extraction``
    JSON keeps the immutable AI snapshot. ``location_status`` preserves explicit
    UNCERTAIN — missing coordinates are never stored as 0,0.
    """

    __tablename__ = "reports"
    __table_args__ = (
        Index("idx_reports_status", "status"),
        Index("idx_reports_verification_status", "verification_status"),
        Index("idx_reports_timestamp", "timestamp"),
        Index("idx_reports_source", "source"),
        Index("idx_reports_location_status", "location_status"),
    )

    report_id: Mapped[str] = mapped_column(Text, primary_key=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    reporter: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = _timestamptz()
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    incident: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    affected_population: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    infrastructure_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    available_needs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    vulnerability: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    time_sensitivity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    original_extraction: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = _timestamptz()


class ReportNeedRow(Base):
    """One row per need carried by a report (normalized for DB filtering).

    ``position`` preserves the original list order from the domain model so a
    report's needs round-trip deterministically.

    The table is ``report_need_records`` — NOT ``report_needs``, which the
    team's ``schema_v2.sql`` already owns with a different shape (``need_id``
    lookup FK, no ``need`` text column). Using the team's name would make the
    migration's CREATE TABLE IF NOT EXISTS a silent no-op and then fail while
    building indexes on the nonexistent ``need`` column. Constraint/index names
    are likewise scoped to this table so they cannot collide with the team's
    ``idx_report_needs_*`` entries.
    """

    __tablename__ = "report_need_records"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "need", name="uq_report_need_records_report_need"
        ),
        Index("idx_report_need_records_need", "need"),
        Index("idx_report_need_records_report", "report_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False
    )
    need: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class VerificationRecordRow(Base):
    """Append-only human verification records.

    Named ``verification_records`` to avoid colliding with the team's older
    ``verifications`` table in schema_v2.sql (which has a different shape).
    Human verification stays distinct from AI extraction: the original report
    text in ``reports`` is never touched by this table.
    """

    __tablename__ = "verification_records"
    __table_args__ = (
        Index("idx_verification_records_report", "report_id"),
        Index("idx_verification_records_timestamp", "timestamp"),
    )

    verification_id: Mapped[str] = mapped_column(Text, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = _timestamptz()
    changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AuditLogRow(Base):
    """Append-only audit log.

    The repository interface exposes no update/delete, so records can only be
    appended. ``old_value``/``new_value`` keep the pre/post structured values
    traceable without duplicating the original report.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_report", "report_id"),
        Index("idx_audit_logs_timestamp", "timestamp"),
    )

    audit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = _timestamptz()
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    new_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ResponseActivityRow(Base):
    """Recorded response activities (Phase 12)."""

    __tablename__ = "response_activities"
    __table_args__ = (
        Index("idx_response_activities_report", "report_id"),
        Index("idx_response_activities_status", "response_status"),
        Index("idx_response_activities_timestamp", "timestamp"),
    )

    response_id: Mapped[str] = mapped_column(Text, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False
    )
    need: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    activity: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = _timestamptz()
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    affected_population: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class FusionCandidateRow(Base):
    """Reviewable duplicate/conflict candidates (Phase 6/7 evidence fusion).

    Candidates are persisted so potential duplicates and conflicts remain
    reviewable: nothing is auto-merged or auto-deleted, and contradictory
    evidence is preserved until a human resolves the candidate.
    """

    __tablename__ = "fusion_candidates"
    __table_args__ = (
        Index("idx_fusion_candidates_status", "status"),
        Index("idx_fusion_candidates_type", "type"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    report_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    cluster_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    similarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _timestamptz()
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PriorityResultRow(Base):
    """Persisted backend-computed priority (Phase 8).

    Holds every factor score, the final score, the derived level, the
    calculation version and the calculation timestamp. Scores are always
    produced by the backend calculation; clients can never write these values.
    """

    __tablename__ = "priority_results"

    report_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reports.report_id", ondelete="CASCADE"), primary_key=True
    )
    severity_score: Mapped[float] = mapped_column(Float, nullable=False)
    affected_population_score: Mapped[float] = mapped_column(Float, nullable=False)
    vulnerability_score: Mapped[float] = mapped_column(Float, nullable=False)
    time_sensitivity_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_verification_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    priority_level: Mapped[str] = mapped_column(Text, nullable=False)
    calculation_version: Mapped[str] = mapped_column(Text, nullable=False)
    calculated_at: Mapped[datetime] = _timestamptz()


def create_all(engine) -> None:
    """Create every known table if it does not exist.

    ``create_all`` is inherently additive (never drops or alters), so it is a
    safe way to bootstrap a fresh database or add missing Phase 15 tables to a
    deployed one. Runs only when explicitly enabled (DB_CREATE_TABLES_ON_STARTUP).
    """
    Base.metadata.create_all(bind=engine)


# Application-required tables (users + the additive Phase 15 tables). Used by
# the startup schema-readiness check; the list is derived from the ORM metadata
# so it can never drift from the models.
REQUIRED_TABLES = tuple(sorted(Base.metadata.tables.keys()))


__all__ = [
    "Base",
    "UserRow",
    "ReportRow",
    "ReportNeedRow",
    "VerificationRecordRow",
    "AuditLogRow",
    "ResponseActivityRow",
    "FusionCandidateRow",
    "PriorityResultRow",
    "REQUIRED_TABLES",
    "create_all",
]