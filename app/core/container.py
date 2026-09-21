"""Application composition root.

Owns the shared repositories and the stateless services built over them, so
routers never reach into sibling routers for data access. Swapping the storage
backend is done in this module only: every ``get_*_repository`` /
``get_*_service`` dependency factory is the swap point, and no router changes.

Storage selection order:

1. PostgreSQL (``DATABASE_URL`` configured) — repositories backed by SQLAlchemy
   2.x over the shared session factory from ``app.core.database``. This is the
   Phase 15 production path; priority results are persisted through the same
   store.
2. File (``use_persistent_db``) — JSON-store repositories under ``data/``.
3. In-memory — default for local development/tests that override dependencies.
"""

from app.conflicts.service import ConflictDetectionService
from app.duplicates.service import DuplicateDetectionService
from app.repositories.fusion_repository import InMemoryFusionRepository, FusionRepository
from app.repositories import (
    InMemoryAuditRepository,
    InMemoryReportRepository,
    InMemoryResponseRepository,
    InMemoryUserRepository,
    InMemoryVerificationRepository,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.response_repository import ResponseRepository
from app.repositories.user_repository import UserRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.auth_service import AuthService
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.services.response_service import ResponseService
from app.services.fusion_service import FusionService
from app.verification.service import VerificationService

from app.repositories.file_repositories import (
    FileFusionRepository,
    FileAuditRepository,
    FileReportRepository,
    FileResponseRepository,
    FileUserRepository,
    FileVerificationRepository,
)
from app.repositories.postgres_repositories import (
    PostgresAuditRepository,
    PostgresFusionRepository,
    PostgresPriorityResultRepository,
    PostgresReportRepository,
    PostgresResponseRepository,
    PostgresUserRepository,
    PostgresVerificationRepository,
)
from app.core.config import settings
from app.core.database import get_session_factory

if settings.database_url.strip():
    _session_factory = get_session_factory()
    report_repository = PostgresReportRepository(_session_factory)
    user_repository = PostgresUserRepository(_session_factory)
    verification_repository = PostgresVerificationRepository(_session_factory)
    audit_repository = PostgresAuditRepository(_session_factory)
    fusion_repository = PostgresFusionRepository(_session_factory)
    response_repository = PostgresResponseRepository(_session_factory)
    priority_result_store = PostgresPriorityResultRepository(_session_factory)
elif settings.use_persistent_db:
    report_repository = FileReportRepository(settings.data_dir)
    user_repository = FileUserRepository(settings.data_dir)
    verification_repository = FileVerificationRepository(settings.data_dir)
    audit_repository = FileAuditRepository(settings.data_dir)
    fusion_repository = FileFusionRepository(settings.data_dir)
    response_repository = FileResponseRepository(settings.data_dir)
    priority_result_store = None
else:
    report_repository = InMemoryReportRepository()
    user_repository = InMemoryUserRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()
    fusion_repository = InMemoryFusionRepository()
    response_repository = InMemoryResponseRepository()
    priority_result_store = None

_auth_service = AuthService(user_repository)
_report_service = ReportService(report_repository)
_priority_service = PriorityService(report_repository, result_store=priority_result_store)
_verification_service = VerificationService(
    report_repository,
    verification_repository,
    audit_repository,
)
_response_service = ResponseService(
    response_repository,
    report_repository,
    audit_repository,
)


def get_user_repository() -> UserRepository:
    """Return the shared in-memory user repository.

    A single instance is created once at import time so users persist across
    requests. Swap the storage backend here (e.g. for a database-backed
    repository) without changing the routers.
    """
    return user_repository


def get_auth_service() -> AuthService:
    """Return the shared auth service over the shared user repository."""
    return _auth_service


def get_report_repository() -> ReportRepository:
    """Return the shared in-memory report repository.

    Exposed so every feature operates on exactly the same reports as the
    reports API. Swap the storage backend here without touching the routers.
    """
    return report_repository


def get_report_service() -> ReportService:
    """Return the shared report service over the shared report repository."""
    return _report_service


def get_verification_repository() -> VerificationRepository:
    """Return the shared in-memory verification repository."""
    return verification_repository


def get_audit_repository() -> AuditRepository:
    """Return the shared in-memory audit repository (append-only)."""
    return audit_repository


def get_verification_service() -> VerificationService:
    """Return the shared verification service over the shared repositories.

    The report repository is the same instance used by the reports API, so
    verification writes are visible everywhere. Storage backends are swapped
    here without changing the router.
    """
    return _verification_service


def get_response_repository() -> ResponseRepository:
    """Return the shared in-memory response repository."""
    return response_repository


def get_response_service() -> ResponseService:
    """Return the shared response service over the shared repositories.

    Responses, reports and the audit log all share the same instances used by
    their own APIs, so recorded activities, validated reports and audit
    entries stay consistent.
    """
    return _response_service


def get_priority_service() -> PriorityService:
    """Return the shared priority service (single source of truth for scores).

    The calculation is fully backend-controlled: the AI never contributes a
    score. Storage is swapped in get_report_repository without touching the
    calculation logic.
    """
    return _priority_service


def get_duplicate_service() -> DuplicateDetectionService:
    """Return the duplicate-detection service over the shared reports.

    Duplicate detection sees exactly the reports created via the reports API.
    Storage is swapped in get_report_repository without changing this factory.
    """
    return DuplicateDetectionService(report_repository)


def get_conflict_service() -> ConflictDetectionService:
    """Return the conflict-detection service over the shared reports.

    Conflict detection sees exactly the reports created via the reports API.
    Storage is swapped in get_report_repository without changing this factory.
    """
    return ConflictDetectionService(report_repository)
_fusion_service = FusionService(fusion_repository)

def get_fusion_repository() -> FusionRepository:
    return fusion_repository

def get_fusion_service() -> FusionService:
    return _fusion_service
