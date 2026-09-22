"""Pytest fixtures shared across the whole test suite (Phase 13 auth setup).

``auth_setup`` seeds an in-memory user repository with one user per role and
overrides the app's user-repository dependency, so any TestClient issued
against ``app`` resolves bearer tokens against those seeded users. The role
header fixtures return ready-to-attach Authorization headers.
"""

import json
from types import SimpleNamespace

import bcrypt
import pytest
from fastapi.testclient import TestClient

import app.services.auth_service as auth_service_module
from app.api.ai import get_ai_service
from app.models.user import UserRole
from tests.helpers import (
    clear_user_repository_override,
    headers_for,
    make_auth_setup,
    override_user_repository,
)


def _fast_hash_password(password: str) -> str:
    """Test-only bcrypt hashing at a very low cost factor.

    Seeding users runs once per fixture-using test; the default cost (rounds
    = 12) would add roughly 1.2s of hashing to every single test. The cost
    factor is a security/performance trade-off that is irrelevant to the
    behaviour under test, so tests force rounds=4. verify_password reads the
    cost from the stored hash, so login checks stay consistent.
    """
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=4)
    ).decode("utf-8")


auth_service_module.hash_password = _fast_hash_password


@pytest.fixture(autouse=True)
def offline_container_fusion(monkeypatch):
    """Keep the whole offline suite hermetic w.r.t. fusion analysis.

    ``ReportService._run_fusion_analysis`` calls
    ``app.core.container.get_fusion_service`` directly (a plain function call,
    NOT a FastAPI dependency), so route-level ``dependency_overrides`` never
    intercept the report-create path. With a real ``DATABASE_URL`` in the
    environment the container therefore builds the live PostgreSQL fusion
    service, making every offline report creation touch the live database.
    That live-network dependence produced the Batch 4 transient failures.

    This autouse fixture swaps the container's fusion service AND its fusion
    repository for one shared in-memory pair for every test, so candidate
    generation (create path), listing, detail and resolve all observe the same
    offline data. Tests that need a specific fusion behavior override the
    container function again via their own monkeypatch, which is applied after
    this one and wins for that test.
    """
    import app.core.container as container_module

    from app.repositories.fusion_repository import InMemoryFusionRepository
    from app.services.fusion_service import FusionService

    repository = InMemoryFusionRepository()
    monkeypatch.setattr(
        container_module, "get_fusion_service", lambda: FusionService(repository)
    )
    monkeypatch.setattr(container_module, "get_fusion_repository", lambda: repository)


@pytest.fixture()
def auth_setup():
    """Fresh seeded users (one per role) wired to the live app.

    Both the user-repository AND the auth-service dependencies point at the
    seeded repository, so request authentication, API registration and API
    login all operate on exactly the same in-memory data as the seeded users.
    """
    from app.api.deps import get_auth_service
    from app.main import app

    setup = make_auth_setup()
    override_user_repository(setup)
    app.dependency_overrides[get_auth_service] = lambda: setup.service
    yield setup
    app.dependency_overrides.pop(get_auth_service, None)
    clear_user_repository_override()


@pytest.fixture()
def admin_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.ADMIN)


@pytest.fixture()
def assessor_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.ASSESSOR)


@pytest.fixture()
def reviewer_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.REVIEWER)


@pytest.fixture()
def responder_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.RESPONDER)


@pytest.fixture()
def viewer_headers(auth_setup) -> dict[str, str]:
    return headers_for(auth_setup, UserRole.VIEWER)


# ---------------------------------------------------------------------------
# Phase 14 integration wiring: a live app whose report/verification/audit/
# response storage and every composite service are overridden with fresh
# shared instances, so cross-feature tests exercise exactly the same wiring
# an operator sees in production. External services (Gemini, geocoding) are
# mocked offline.
# ---------------------------------------------------------------------------

_VALID_AI_JSON = json.dumps(
    {
        "incident": "Flood",
        "location": "kozhikode beach",
        "needs": ["WATER", "FOOD"],
        "severity": "HIGH",
        "affected_population": 500,
        "vulnerability": ["children", "elderly"],
        "time_sensitivity": "needs water within 24 hours",
        "evidence": ["no clean drinking water since yesterday"],
    }
)


class _ScriptedAIClient:
    """AIClient stand-in returning fixed scripted Gemini output."""

    def __init__(self, raw: str = _VALID_AI_JSON) -> None:
        self.raw = raw

    def generate_json(self, *, system_instruction: str, prompt: str) -> str:
        return self.raw


@pytest.fixture()
def storage_repos() -> SimpleNamespace:
    from app.repositories import (
        InMemoryAuditRepository,
        InMemoryReportRepository,
        InMemoryResponseRepository,
        InMemoryVerificationRepository,
    )

    return SimpleNamespace(
        reports=InMemoryReportRepository(),
        responses=InMemoryResponseRepository(),
        verifications=InMemoryVerificationRepository(),
        audit=InMemoryAuditRepository(),
    )


@pytest.fixture()
def app_client(auth_setup, admin_headers, storage_repos) -> TestClient:
    """Every repository-consuming dependency wired to the same fresh storage.

    Reports, verification, audit, response activities, priority, duplicates,
    conflicts, search, map, information gaps and coverage all operate on the
    exact same in-memory data. Gemini is replaced with a scripted fake and
    geocoding uses the offline StubGeocoder, so the whole pipeline is
    deterministic and requires no external service.
    """
    from fastapi.testclient import TestClient

    from app.api.analytics import get_response_coverage_service
    from app.api.conflicts import get_conflict_service
    from app.api.duplicates import get_duplicate_service
    from app.api.map import get_information_gap_service, get_map_service
    from app.api.map_responses import get_response_map_service
    from app.api.priority import get_priority_service
    from app.api.reports import get_report_service
    from app.api.responses import get_response_repository, get_response_service
    from app.api.search import get_search_service
    from app.api.verification import get_audit_repository, get_verification_service
    from app.conflicts.service import ConflictDetectionService
    from app.duplicates.service import DuplicateDetectionService
    from app.location.providers import StubGeocoder
    from app.location.service import LocationService
    from app.main import app
    from app.services.ai_service import AIService
    from app.services.information_gap_service import InformationGapService
    from app.services.map_service import MapService
    from app.services.priority_service import PriorityService
    from app.services.report_service import ReportService
    from app.services.response_coverage_service import ResponseCoverageService
    from app.services.response_map_service import ResponseMapService
    from app.services.response_service import ResponseService
    from app.search.service import SearchService
    from app.verification.service import VerificationService

    reports = storage_repos.reports
    responses = storage_repos.responses
    verifications = storage_repos.verifications
    audit = storage_repos.audit
    location = LocationService(StubGeocoder())
    priority = PriorityService(reports)
    search = SearchService(reports, priority, location)

    app.dependency_overrides[get_report_service] = (
        lambda: ReportService(reports, audit, priority_service=priority)
    )
    app.dependency_overrides[get_verification_service] = (
        lambda: VerificationService(reports, verifications, audit)
    )
    app.dependency_overrides[get_audit_repository] = lambda: audit
    app.dependency_overrides[get_priority_service] = lambda: priority
    app.dependency_overrides[get_duplicate_service] = (
        lambda: DuplicateDetectionService(reports)
    )
    app.dependency_overrides[get_conflict_service] = (
        lambda: ConflictDetectionService(reports)
    )
    app.dependency_overrides[get_response_repository] = lambda: responses
    app.dependency_overrides[get_response_service] = (
        lambda: ResponseService(responses, reports, audit)
    )
    app.dependency_overrides[get_search_service] = lambda: search
    app.dependency_overrides[get_map_service] = (
        lambda: MapService(
            SearchService(reports, PriorityService(reports), location),
            location,
        )
    )
    app.dependency_overrides[get_information_gap_service] = (
        lambda: InformationGapService(reports, location)
    )
    app.dependency_overrides[get_response_map_service] = (
        lambda: ResponseMapService(responses, location)
    )
    app.dependency_overrides[get_response_coverage_service] = (
        lambda: ResponseCoverageService(reports, responses, priority)
    )
    app.dependency_overrides[get_ai_service] = lambda: AIService(_ScriptedAIClient())

    with TestClient(app) as client:
        client.headers.update(admin_headers)
        yield client
    app.dependency_overrides.clear()
import os
os.environ['USE_PERSISTENT_DB'] = 'false'
