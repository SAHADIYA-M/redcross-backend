"""Pytest fixtures shared across the whole test suite (open API).

The API is unauthenticated: no user repository is seeded and no client
carries an Authorization header, so every request exercises the same
public-open path an operator sees in production.

The offline suite is hermetic: it must NEVER touch a live database, so the
container is forced to in-memory storage (DATABASE_URL cleared +
USE_PERSISTENT_DB=false) BEFORE any ``app`` module is imported.
"""

import json
import os
from types import SimpleNamespace

os.environ["USE_PERSISTENT_DB"] = "false"
os.environ["DATABASE_URL"] = ""

import pytest
from fastapi.testclient import TestClient

from app.api.ai import get_ai_service


@pytest.fixture(autouse=True)
def offline_container_fusion(monkeypatch):
    """Keep the whole offline suite hermetic w.r.t. fusion analysis.

    ``ReportService._run_fusion_analysis`` calls
    ``app.core.container.get_fusion_service`` directly (a plain function call,
    NOT a FastAPI dependency), so the container itself must be patched for the
    report-create path. The fusion ROUTER dependencies import their factory
    functions from the container at import time, so they hold stale copies and
    must be pinned via ``dependency_overrides`` to the SAME shared in-memory
    pair — otherwise creation writes to one repository and listing reads
    another (or, with a configured DATABASE_URL, a live database).

    This autouse fixture wires one shared in-memory fusion pair to BOTH the
    container and the router dependencies, so candidate generation (create
    path), listing, detail and resolve all observe the same offline data.
    Tests that need a specific fusion behavior override the container
    function again via their own monkeypatch or dependency_overrides, which
    are applied after this one and win for that test.
    """
    import app.core.container as container_module

    from app.repositories.fusion_repository import InMemoryFusionRepository
    from app.services.fusion_service import FusionService

    repository = InMemoryFusionRepository()
    monkeypatch.setattr(
        container_module, "get_fusion_service", lambda: FusionService(repository)
    )
    monkeypatch.setattr(container_module, "get_fusion_repository", lambda: repository)

    from app.api.fusion import get_fusion_repository, get_fusion_service
    from app.main import app

    app.dependency_overrides[get_fusion_service] = (
        lambda: FusionService(repository)
    )
    app.dependency_overrides[get_fusion_repository] = lambda: repository
    yield
    app.dependency_overrides.pop(get_fusion_repository, None)
    app.dependency_overrides.pop(get_fusion_service, None)


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
def app_client(storage_repos) -> TestClient:
    """Every repository-consuming dependency wired to the same fresh storage.

    Reports, verification, audit, response activities, priority, duplicates,
    conflicts, search, map, information gaps and coverage all operate on the
    exact same in-memory data. Gemini is replaced with a scripted fake and
    geocoding uses the offline StubGeocoder, so the whole pipeline is
    deterministic and requires no external service. The client sends NO
    Authorization header — every endpoint is public.
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
        yield client
    app.dependency_overrides.clear()