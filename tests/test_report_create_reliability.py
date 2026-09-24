"""Batch 2 regression tests: report-creation performance + error handling.

Verifies that report creation still triggers fusion candidate analysis but:
- does not scan the whole reports table (no ``get_all()`` on the report repo);
- retrieves only the reports in the new report's fusion cluster;
- the fusion analysis itself loads only the current cluster's candidates, never
  the whole fusion-candidates table;
- a fused report that is already persisted is never reported as a failed
  create: expected (recoverable) fusion-store failures and unexpected fusion
  failures are logged but the already-persisted report is returned, so a
  client cannot be misled into resubmitting (which would create a duplicate).

All tests run fully offline: the fusion service is swapped for an in-memory
stand-in and the report repository is an in-memory implementation.
"""

import pytest

import app.core.container as container_module
from app.ai.schemas import NeedCategory
from app.core.database import DatabaseUnavailableError
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_report_repository import InMemoryReportRepository
from app.repositories.fusion_repository import InMemoryFusionRepository
from app.schemas.report import CreateReport
from app.services.fusion_service import FusionService
from app.services.report_service import ReportService


class _SpyReportRepository(InMemoryReportRepository):
    """In-memory report repo that records how the create path queries it."""

    def __init__(self) -> None:
        super().__init__()
        self.get_all_calls = 0
        self.cluster_calls: list[tuple[str, str]] = []

    def get_all(self):
        self.get_all_calls += 1
        return super().get_all()

    def get_cluster_candidates(self, location: str, need: str):
        self.cluster_calls.append((location, need))
        return super().get_cluster_candidates(location, need)


class _RaisingFusionService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def analyze_cluster(self, cluster_id: str, reports: list) -> None:
        raise self.error


def _make_service(repository=None) -> tuple[ReportService, _SpyReportRepository]:
    repo = repository or _SpyReportRepository()
    return ReportService(repo, InMemoryAuditRepository()), repo


def _install_fusion(monkeypatch, service) -> None:
    monkeypatch.setattr(container_module, "get_fusion_service", lambda: service)


# ---------------------------------------------------------------------------
# Targeted retrieval: no full-table scan on the create path
# ---------------------------------------------------------------------------


def test_report_create_does_not_call_get_all(monkeypatch) -> None:
    fusion_repo = InMemoryFusionRepository()
    _install_fusion(monkeypatch, FusionService(fusion_repo))
    service, repo = _make_service()

    service.create(
        CreateReport(
            original_text="500 families need water",
            reporter="team_a",
            location="Area X",
            needs=[NeedCategory.WATER],
        )
    )
    service.create(
        CreateReport(
            original_text="500 families need water",
            reporter="team_a",
            location="Area X",
            needs=[NeedCategory.WATER],
        )
    )

    # The previous implementation called get_all() on every create.
    assert repo.get_all_calls == 0
    # The targeted cluster retrieval was used instead.
    assert ("Area X", NeedCategory.WATER.value) in repo.cluster_calls
    # And fusion still ran against the persisted cluster members.
    candidates = fusion_repo.get_all()
    assert any(c.type.value == "POSSIBLE_DUPLICATE" for c in candidates)


def test_report_create_still_returns_created_report(monkeypatch) -> None:
    _install_fusion(monkeypatch, FusionService(InMemoryFusionRepository()))
    service, _ = _make_service()

    created = service.create(
        CreateReport(
            original_text="bridge washed away",
            reporter="team_a",
            location="Kozhikode",
            needs=[NeedCategory.WATER],
        )
    )
    assert created.id
    assert created.original_text == "bridge washed away"
    assert created.cluster_location == "Kozhikode"
    assert created.cluster_need == NeedCategory.WATER.value


def test_get_cluster_candidates_only_returns_same_cluster(monkeypatch) -> None:
    _install_fusion(monkeypatch, FusionService(InMemoryFusionRepository()))
    repo = InMemoryReportRepository()
    service = ReportService(repo, InMemoryAuditRepository())

    a1 = service.create(
        CreateReport(
            original_text="duplicate text",
            reporter="team_a",
            location="Area A",
            needs=[NeedCategory.WATER],
        )
    )
    service.create(
        CreateReport(
            original_text="different area report",
            reporter="team_a",
            location="Area B",
            needs=[NeedCategory.WATER],
        )
    )
    a2 = service.create(
        CreateReport(
            original_text="duplicate text",
            reporter="team_a",
            location="Area A",
            needs=[NeedCategory.WATER],
        )
    )

    candidates = repo.get_cluster_candidates("Area A", NeedCategory.WATER.value)
    assert {report.id for report in candidates} == {a1.id, a2.id}


def test_no_need_reports_share_general_request_cluster(monkeypatch) -> None:
    _install_fusion(monkeypatch, FusionService(InMemoryFusionRepository()))
    repo = InMemoryReportRepository()
    service = ReportService(repo, InMemoryAuditRepository())

    first = service.create(
        CreateReport(original_text="no structured needs", reporter="team_a", location="Area X")
    )
    second = service.create(
        CreateReport(original_text="no structured needs", reporter="team_a", location="Area X")
    )

    # Reports without structured needs fall into the General Request cluster and
    # are only comparable to other reports in the same cluster.
    all_cluster = repo.get_cluster_candidates("Area X", "General Request")
    assert {r.id for r in all_cluster} == {first.id, second.id}
    assert repo.get_cluster_candidates("Unknown Location", "General Request") == []


# ---------------------------------------------------------------------------
# Error handling: expected and unexpected fusion failures
# ---------------------------------------------------------------------------


def test_successful_create_when_fusion_succeeds(monkeypatch) -> None:
    _install_fusion(monkeypatch, FusionService(InMemoryFusionRepository()))
    service, repo = _make_service()

    created = service.create(
        CreateReport(
            original_text="normal report",
            reporter="team_a",
            location="Area X",
            needs=[NeedCategory.WATER],
        )
    )
    assert repo.get_by_id(created.id) is not None


def test_expected_fusion_store_failure_does_not_fail_persisted_create(
    monkeypatch, caplog
) -> None:
    """A recoverable fusion-store failure on the create path is logged, never
    a fake create failure: the report is already durably persisted, so turning
    the request into a 503 would prompt clients to resubmit and create a
    duplicate."""
    _install_fusion(
        monkeypatch,
        _RaisingFusionService(DatabaseUnavailableError("fusion store down")),
    )
    service, repo = _make_service()

    import logging

    with caplog.at_level(logging.WARNING):
        created = service.create(
            CreateReport(
                original_text="report kept even if fusion fails",
                reporter="team_a",
                location="Area X",
                needs=[NeedCategory.WATER],
            )
        )
    # The create succeeds: the report is returned and persisted.
    assert repo.get_by_id(created.id) is not None
    assert created.original_text == "report kept even if fusion fails"
    # The failure is surfaced in the logs, not silently swallowed.
    assert any(
        "Fusion candidate analysis did not complete" in record.message
        for record in caplog.records
    )


def test_unexpected_fusion_failure_does_not_fail_persisted_create(
    monkeypatch, caplog
) -> None:
    """An unexpected fusion failure is logged as an error but never fails the
    already-persisted report: intake reliability outranks a background-quality
    candidate write."""
    _install_fusion(monkeypatch, _RaisingFusionService(RuntimeError("boom")))
    service, repo = _make_service()

    import logging

    with caplog.at_level(logging.ERROR):
        created = service.create(
            CreateReport(
                original_text="unexpected failure is logged, not fatal",
                reporter="team_a",
                location="Area X",
                needs=[NeedCategory.WATER],
            )
        )
    # No data loss and no propagated exception: the report is returned.
    assert repo.get_by_id(created.id) is not None
    assert created.original_text == "unexpected failure is logged, not fatal"
    # It is not silently swallowed either: an error record exists.
    assert any(
        "Unexpected failure during fusion analysis" in record.message
        for record in caplog.records
    )