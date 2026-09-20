"""Application composition root.

Owns the shared in-memory repositories and the stateless services built over
them, so routers never reach into sibling routers for data access. Swapping
the storage backend for PostgreSQL later is done in this module only:
every ``get_*_repository`` / ``get_*_service`` dependency factory is the swap
point, and no router changes.

- repositories: shared module singletons (report, user, verification, audit,
  response) so every feature operates on the same in-memory data;
- services: either module singletons (auth, report, priority, verification,
  response) or cheap per-request builds with no shared state.

Feature routers that additionally need a geocoder-backed LocationService keep
their own thin factories wired through ``app.api.geocoder_deps``; they consume
repositories/priority from here.
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
from app.core.config import settings

if settings.use_persistent_db:
    report_repository = FileReportRepository(settings.data_dir)
    user_repository = FileUserRepository(settings.data_dir)
    verification_repository = FileVerificationRepository(settings.data_dir)
    audit_repository = FileAuditRepository(settings.data_dir)
    fusion_repository = FileFusionRepository(settings.data_dir)
    response_repository = FileResponseRepository(settings.data_dir)
else:
    report_repository = InMemoryReportRepository()
    user_repository = InMemoryUserRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()
    fusion_repository = InMemoryFusionRepository()
    response_repository = InMemoryResponseRepository()

_auth_service = AuthService(user_repository)
_report_service = ReportService(report_repository)
_priority_service = PriorityService(report_repository)
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
