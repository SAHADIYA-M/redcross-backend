"""Batch 5 hardening regression tests.

Covers the Batch 5 fixes:

1. Fusion candidate identity is cluster- and type-scoped. A candidate id
   derives from (cluster, type, report pair), so:
   - analysing the same pair under two clusters never clobbers the first
     cluster's candidate; and
   - a pair that is BOTH a possible duplicate and a possible conflict yields
     two distinct candidates instead of one overwriting the other.
   Analysis still never scans the whole ``fusion_candidates`` table
   (cluster-scoped loads only), and already-persisted candidates are re-used
   instead of re-saved.
2. A persisted report is never reported as a failed create because the
   background-quality fusion candidate write failed (Batch 4 transient 503
   regression): the failure is logged and the report is returned.
3. Verification EDIT recomputes priority through the application's shared
   PriorityService, so the result is persisted to (or invalidated from) the
   same result store the priority API uses - never a store-less copy.
4. Oversized free-text filter/substring parameters are rejected (422) instead
   of being scanned for.
5. Map point lists are bounded pages with ``limit``/``offset``; ``total``
   always reports the full matching count.
6. ``GET /api/fusion`` returns a bounded, deterministically ordered page.
"""

from datetime import datetime, timedelta, timezone

from app.ai.schemas import SeverityLevel
from app.models.fusion import FusionCandidate, FusionStatus, FusionType
from app.models.report import Report
from app.repositories.fusion_repository import InMemoryFusionRepository
from app.schemas.lengths import (
    MAX_INCIDENT_LENGTH,
    MAX_LOCATION_LENGTH,
    MAX_QUERY_LENGTH,
    MAX_REPORT_ID_LENGTH,
    MAX_SOURCE_LENGTH,
)
from app.services.fusion_service import FusionService


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _report(index: int, text: str, **overrides) -> Report:
    values = {
        "id": f"r-{index}",
        "original_text": text,
        "reporter": "team_a",
        "timestamp": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return Report(**values)


class _NoGetAllRepository(InMemoryFusionRepository):
    """In-memory fusion repo that makes a full-table load fatal.

    Existing candidates are only ever loaded per cluster (``get_by_cluster``);
    a `get_all` call during analysis would re-introduce the Batch 4
    full-table-scan bug and must fail loudly whenever it happens.
    """

    def get_all(self):
        raise AssertionError("analyze_cluster must not scan the whole table")


def _override_fusion_repository(app_client, repo: InMemoryFusionRepository) -> None:
    """Point the live fused app's fusion listing at ``repo``.

    ``app.api.fusion.get_fusion_repository`` is the exact callable the route
    captured at app construction time (after the autouse conftest fixture has
    patched the container), so registering it in ``dependency_overrides`` is
    hermetic under FastAPI's lazy-router internals.
    """
    from app.api.fusion import get_fusion_repository

    app_client.app.dependency_overrides[get_fusion_repository] = lambda: repo


def _create_report(
    client, *, text: str, location: str = "Area X", needs: list[str] | None = None
) -> dict:
    payload = {"original_text": text, "reporter": "team_a", "location": location}
    if needs is not None:
        payload["needs"] = needs
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class _RaisingFusionService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def analyze_cluster(self, cluster_id: str, reports: list) -> None:
        raise self.error


class _RecordingPriorityStore:
    """Result store spy that records every backend save/invalidation."""

    def __init__(self) -> None:
        self.saved: list = []
        self.deleted: list[str] = []

    def save(self, result) -> None:
        self.saved.append(result)

    def delete_by_report(self, report_id: str) -> None:
        self.deleted.append(report_id)


# ---------------------------------------------------------------------------
# Fix 1a: fusion candidate identity is cluster-scoped (no cross-cluster clobber)
# ---------------------------------------------------------------------------


def test_fusion_candidates_survive_same_pair_in_two_clusters() -> None:
    repo = _NoGetAllRepository()
    fused = FusionService(repo)
    reports = [_report(1, "identical water request"), _report(2, "identical water request")]

    fused.analyze_cluster("CLUSTER-A", reports)
    fused.analyze_cluster("CLUSTER-B", reports)

    # Analysing the same pair under a second cluster must not overwrite the
    # first cluster's candidate: candidates are identity-scoped per cluster.
    cluster_a = repo.get_by_cluster("CLUSTER-A")
    cluster_b = repo.get_by_cluster("CLUSTER-B")
    assert len(cluster_a) == 1
    assert len(cluster_b) == 1
    assert cluster_a[0].cluster_id == "CLUSTER-A"
    assert cluster_b[0].cluster_id == "CLUSTER-B"
    assert {candidate.type for candidate in cluster_a} == {FusionType.POSSIBLE_DUPLICATE}
    # Distinct ids: id material includes the cluster id.
    assert cluster_a[0].id != cluster_b[0].id
    assert len({candidate.id for candidate in cluster_a + cluster_b}) == 2


def test_fusion_dual_duplicate_and_conflict_candidates_both_persist() -> None:
    """A pair that is both a duplicate and a conflict keeps BOTH candidates.

    Text similarity >= 0.60 produces a POSSIBLE_DUPLICATE; a CRITICAL-vs-LOW
    severity pair produces a POSSIBLE_CONFLICT for the same report pair. The
    candidate id must scope by type too, otherwise the second candidate is
    dropped before it reaches the reviewer queue.
    """
    repo = _NoGetAllRepository()
    fused = FusionService(repo)
    reports = [
        _report(1, "plain identical request", severity=SeverityLevel.CRITICAL),
        _report(2, "plain identical request", severity=SeverityLevel.LOW),
    ]

    fused.analyze_cluster("CLUSTER-X", reports)

    candidates = repo.get_by_cluster("CLUSTER-X")
    assert {candidate.type for candidate in candidates} == {
        FusionType.POSSIBLE_DUPLICATE,
        FusionType.POSSIBLE_CONFLICT,
    }
    assert len({candidate.id for candidate in candidates}) == 2


def test_fusion_reuses_existing_candidates_not_resaved() -> None:
    repo = _NoGetAllRepository()
    fused = FusionService(repo)
    reports = [_report(1, "duplicate pair body"), _report(2, "duplicate pair body")]

    fused.analyze_cluster("CLUSTER-A", reports)
    first_round_ids = {candidate.id for candidate in repo.get_by_cluster("CLUSTER-A")}
    assert len(first_round_ids) == 1

    # Re-analysing the same cluster with the same reports must not duplicate
    # the already-persisted candidates.
    fused.analyze_cluster("CLUSTER-A", reports)
    assert {candidate.id for candidate in repo.get_by_cluster("CLUSTER-A")} == first_round_ids


# ---------------------------------------------------------------------------
# Fix 2: persisted reports are never turned into failed creates
# ---------------------------------------------------------------------------


def test_api_report_create_succeeds_when_fusion_fails(
    app_client, monkeypatch, caplog
) -> None:
    import logging

    import app.core.container as container_module

    monkeypatch.setattr(
        container_module,
        "get_fusion_service",
        lambda: _RaisingFusionService(RuntimeError("boom")),
    )

    with caplog.at_level(logging.ERROR):
        created = _create_report(
            app_client, text="intake survives a fusion outage"
        )

    assert created["original_text"] == "intake survives a fusion outage"
    stored = app_client.get(f"/api/reports/{created['id']}")
    assert stored.status_code == 200
    assert stored.json()["original_text"] == "intake survives a fusion outage"
    assert any(
        "Unexpected failure during fusion analysis" in record.message
        for record in caplog.records
    )


def test_api_report_create_succeeds_when_fusion_store_down(
    app_client, monkeypatch, caplog
) -> None:
    import logging

    from app.core.database import DatabaseUnavailableError

    import app.core.container as container_module

    monkeypatch.setattr(
        container_module,
        "get_fusion_service",
        lambda: _RaisingFusionService(DatabaseUnavailableError("store down")),
    )

    with caplog.at_level(logging.WARNING):
        created = _create_report(
            app_client, text="intake survives a fusion-store outage"
        )

    assert created["original_text"] == "intake survives a fusion-store outage"
    assert any(
        "Fusion candidate analysis did not complete" in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Fix 3: verification EDIT uses the shared priority service (and its store)
# ---------------------------------------------------------------------------


def _verification_repos(report: Report):
    from app.repositories import (
        InMemoryAuditRepository,
        InMemoryReportRepository,
        InMemoryVerificationRepository,
    )
    from app.services.priority_service import PriorityService
    from app.verification.service import VerificationService

    reports = InMemoryReportRepository()
    reports.create(report)
    verifications = InMemoryVerificationRepository()
    audit = InMemoryAuditRepository()
    store = _RecordingPriorityStore()
    priority = PriorityService(reports, result_store=store)
    service = VerificationService(
        reports, verifications, audit, priority_service=priority
    )
    return reports, verifications, audit, store, priority, service


def test_verification_edit_persists_priority_through_injected_service() -> None:
    from app.schemas.verification import VerifyRequest
    from app.verification.schemas import VerificationAction, VerificationEdits

    report = _report(
        1,
        "flood damaged homes",
        severity=SeverityLevel.HIGH,
        affected_population=500,
    )
    _, _, _, store, _, service = _verification_repos(report)

    result = service.verify(
        "r-1",
        VerifyRequest(
            action=VerificationAction.EDIT,
            edits=VerificationEdits(affected_population=900),
        ),
    )

    assert result.priority is not None
    assert store.saved, "EDIT must persist the recomputed priority, not a store-less copy"
    assert store.saved[-1].report_id == "r-1"
    assert store.saved[-1].final_score == result.priority.final_score
    assert store.deleted == []


def test_verification_edit_invalidates_stale_priority_when_signal_removed() -> None:
    from app.schemas.verification import VerifyRequest
    from app.verification.schemas import VerificationAction, VerificationEdits

    report = _report(
        1,
        "urgent flood relief",
        severity=SeverityLevel.HIGH,
        affected_population=400,
    )
    _, _, _, store, priority, service = _verification_repos(report)

    # A direct backend calculation first persists a result for the report.
    priority.calculate_for_report("r-1")
    assert len(store.saved) == 1

    # A reviewer edits away every priority-relevant claim: the recomputation
    # finds no usable priority input and must invalidate the stale row. Null
    # for list-typed claims is normalized to the empty list, so the edit never
    # surfaces a 500.
    result = service.verify(
        "r-1",
        VerifyRequest(
            action=VerificationAction.EDIT,
            edits=VerificationEdits(
                severity=None,
                affected_population=None,
                vulnerability=None,
                time_sensitivity=None,
            ),
        ),
    )

    assert result.priority is None
    assert store.deleted == ["r-1"]
    updated = service._report_repository.get_by_id("r-1")
    assert updated is not None
    assert updated.vulnerability == []


def test_verification_edit_clears_a_null_list_claim_without_error(
    app_client,
) -> None:
    """A reviewer clearing a list claim with ``null`` must not trigger a 500.

    Regression: ``VerificationEdits.vulnerability=null`` used to be applied
    verbatim to the Report model, where a list field cannot be null, producing
    a validation error instead of a clean edit.
    """
    created = app_client.post(
        "/api/reports",
        json={
            "original_text": "children vulnerable to waterborne disease",
            "reporter": "team_a",
            "location": "Area X",
            "vulnerability": ["children", "elderly"],
        },
    )
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]

    response = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "EDIT", "edits": {"vulnerability": None}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["vulnerability"] == []
    assert body["report"]["verification_status"] == "VERIFIED"


# ---------------------------------------------------------------------------
# Fix 4: oversized free-text filter parameters are rejected
# ---------------------------------------------------------------------------


def test_search_oversized_free_text_params_rejected(app_client) -> None:
    too_long = "x" * (MAX_QUERY_LENGTH + 1)
    assert app_client.get("/api/search/reports", params={"q": too_long}).status_code == 422
    assert (
        app_client.get(
            "/api/search/reports", params={"location": "x" * (MAX_LOCATION_LENGTH + 1)}
        ).status_code
        == 422
    )
    assert (
        app_client.get(
            "/api/search/reports", params={"incident": "x" * (MAX_INCIDENT_LENGTH + 1)}
        ).status_code
        == 422
    )
    assert (
        app_client.get(
            "/api/search/reports", params={"source": "x" * (MAX_SOURCE_LENGTH + 1)}
        ).status_code
        == 422
    )


def test_search_q_accepts_a_large_but_legit_query(app_client) -> None:
    q = "y" * MAX_QUERY_LENGTH
    assert app_client.get("/api/search/reports", params={"q": q}).status_code == 200


def test_map_oversized_string_params_rejected(app_client) -> None:
    assert (
        app_client.get(
            "/api/map/reports", params={"incident": "x" * (MAX_INCIDENT_LENGTH + 1)}
        ).status_code
        == 422
    )
    assert (
        app_client.get(
            "/api/map/reports", params={"source": "x" * (MAX_SOURCE_LENGTH + 1)}
        ).status_code
        == 422
    )
    assert (
        app_client.get(
            "/api/map/responses", params={"source": "x" * (MAX_SOURCE_LENGTH + 1)}
        ).status_code
        == 422
    )
    assert (
        app_client.get(
            "/api/map/responses", params={"report_id": "x" * (MAX_REPORT_ID_LENGTH + 1)}
        ).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# Fix 5: map point lists are bounded pages
# ---------------------------------------------------------------------------


def test_map_reports_paginates(app_client) -> None:
    for i in range(3):
        _create_report(
            app_client,
            text=f"map point number {i}",
            location="kozhikode beach",
            needs=["WATER"],
        )

    first = app_client.get("/api/map/reports", params={"limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["total"] == 3

    second = app_client.get(
        "/api/map/reports", params={"limit": 2, "offset": 2}
    ).json()
    assert len(second["items"]) == 1
    assert second["total"] == 3
    assert {item["report_id"] for item in first["items"]}.isdisjoint(
        {item["report_id"] for item in second["items"]}
    )


def test_map_reports_default_page_returns_all_when_small(app_client) -> None:
    for i in range(3):
        _create_report(
            app_client,
            text=f"small map {i}",
            location="kozhikode beach",
            needs=["WATER"],
        )
    result = app_client.get("/api/map/reports").json()
    assert len(result["items"]) == 3
    assert result["total"] == 3


def test_map_reports_rejects_out_of_range_limit(app_client) -> None:
    assert app_client.get("/api/map/reports", params={"limit": 0}).status_code == 422
    assert app_client.get("/api/map/reports", params={"limit": 1001}).status_code == 422
    assert app_client.get("/api/map/reports", params={"offset": -1}).status_code == 422


def test_map_responses_paginates(app_client) -> None:
    report = _create_report(
        app_client, text="response map source", location="kozhikode beach", needs=["FOOD"]
    )
    for i in range(2):
        response = app_client.post(
            "/api/responses",
            json={
                "report_id": report["id"],
                "need": "FOOD",
                "activity": f"delivery {i}",
                "response_status": "COMPLETED",
                "location": "kozhikode beach",
            },
        )
        assert response.status_code == 201, response.text

    first = app_client.get("/api/map/responses", params={"limit": 1}).json()
    assert len(first["items"]) == 1
    assert first["total"] == 2

    second = app_client.get(
        "/api/map/responses", params={"limit": 1, "offset": 1}
    ).json()
    assert len(second["items"]) == 1
    assert second["total"] == 2
    assert first["items"][0]["response_id"] != second["items"][0]["response_id"]


# ---------------------------------------------------------------------------
# Fix 6: fusion candidate listing is a bounded, deterministic page
# ---------------------------------------------------------------------------


def _seeded_fusion_repo(count: int) -> InMemoryFusionRepository:
    repo = InMemoryFusionRepository()
    base = datetime(2026, 9, 20, tzinfo=timezone.utc)
    for i in range(count):
        repo.save(
            FusionCandidate(
                id=f"FUS-SEED-{i:04d}",
                type=FusionType.POSSIBLE_DUPLICATE,
                report_ids=[f"r{i}", f"r{i}-b"],
                cluster_id="CLUSTER-SEED",
                reason=f"seed candidate {i}",
                similarity=0.9,
                status=FusionStatus.PENDING,
                created_at=base + timedelta(minutes=i),
            )
        )
    return repo


def test_fusion_list_is_bounded_and_ordered(app_client) -> None:
    repo = _seeded_fusion_repo(5)
    _override_fusion_repository(app_client, repo)

    page1 = app_client.get("/api/fusion", params={"limit": 2}).json()
    assert [candidate["id"] for candidate in page1] == ["FUS-SEED-0000", "FUS-SEED-0001"]

    page2 = app_client.get("/api/fusion", params={"limit": 2, "offset": 2}).json()
    assert [candidate["id"] for candidate in page2] == ["FUS-SEED-0002", "FUS-SEED-0003"]

    tail = app_client.get("/api/fusion", params={"offset": 4}).json()
    assert [candidate["id"] for candidate in tail] == ["FUS-SEED-0004"]


def test_fusion_list_default_limit_caps_response(app_client) -> None:
    from app.schemas.lengths import DEFAULT_LIST_LIMIT

    repo = _seeded_fusion_repo(DEFAULT_LIST_LIMIT + 5)
    _override_fusion_repository(app_client, repo)

    page = app_client.get("/api/fusion").json()
    assert len(page) == DEFAULT_LIST_LIMIT


def test_fusion_list_status_filter_still_applies(app_client) -> None:
    repo = InMemoryFusionRepository()
    base = datetime(2026, 9, 20, tzinfo=timezone.utc)
    repo.save(FusionCandidate(id="A1", type=FusionType.POSSIBLE_DUPLICATE,
                              report_ids=["a", "b"], cluster_id="C1", reason="a",
                              status=FusionStatus.PENDING, created_at=base))
    repo.save(FusionCandidate(id="A2", type=FusionType.POSSIBLE_CONFLICT,
                              report_ids=["c", "d"], cluster_id="C1", reason="b",
                              status=FusionStatus.RESOLVED,
                              created_at=base + timedelta(minutes=1)))
    _override_fusion_repository(app_client, repo)

    # The endpoint's default view is the reviewer's pending queue.
    default = app_client.get("/api/fusion").json()
    assert [candidate["id"] for candidate in default] == ["A1"]
    pending = app_client.get("/api/fusion", params={"status": "PENDING"}).json()
    assert [candidate["id"] for candidate in pending] == ["A1"]
    resolved = app_client.get("/api/fusion", params={"status": "RESOLVED"}).json()
    assert [candidate["id"] for candidate in resolved] == ["A2"]


def test_fusion_list_rejects_out_of_range_limit(app_client) -> None:
    repo = _seeded_fusion_repo(1)
    _override_fusion_repository(app_client, repo)
    assert app_client.get("/api/fusion", params={"limit": 0}).status_code == 422
    assert app_client.get("/api/fusion", params={"limit": 1001}).status_code == 422
    assert app_client.get("/api/fusion", params={"offset": -1}).status_code == 422