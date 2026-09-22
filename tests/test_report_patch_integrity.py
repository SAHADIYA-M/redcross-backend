"""Batch 1 report PATCH security & data-integrity tests.

Covers, through the live API and the service layer:
- PATCH authorization (authentication + writer role);
- the audit actor always coming from the authenticated token, never the body;
- immutable original evidence (``original_text`` cannot be patched);
- one append-only audit record per effective PATCH;
- priority recalculation/invalidation after priority-relevant changes and no
  needless recalculation for unrelated changes;
- verification/duplicate invariants preserved across a PATCH.
"""

from datetime import datetime, timezone

from app.ai.schemas import SeverityLevel
from app.audit.schemas import AuditAction
from app.models.report import Report
from app.models.user import User, UserRole
from app.repositories import InMemoryAuditRepository, InMemoryReportRepository
from app.schemas.auth import UserUpdate
from app.schemas.report import UpdateReport
from app.services.priority_service import PriorityService, priority_level_for_score
from app.services.report_service import ReportService
from tests.helpers import headers_for

_ACTOR = User(
    user_id="actor-1",
    username="assessor_user",
    password_hash="not-a-real-hash",
    role=UserRole.ASSESSOR,
)


def _create(client, **overrides) -> dict:
    payload = {
        "original_text": "500 families need clean drinking water after the flood",
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "incident": "Flood",
        "source": "FIELD_REPORT",
        "needs": ["WATER"],
        "severity": "HIGH",
        "affected_population": 500,
        "vulnerability": ["children"],
        "time_sensitivity": "within 24 hours",
        "evidence": ["no clean drinking water"],
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _update_audits(client, report_id: str) -> list[dict]:
    records = client.get(
        "/api/audit", params={"report_id": report_id}
    ).json()
    return [
        record
        for record in records
        if record["action"] == AuditAction.UPDATE_REPORT.value
    ]


# ---------------------------------------------------------------------------
# 3. PATCH authorization
# ---------------------------------------------------------------------------


def test_unauthenticated_patch_is_rejected(app_client) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    report = _create(app_client)
    with TestClient(app) as bare:
        response = bare.patch(
            f"/api/reports/{report['id']}", json={"status": "IN_REVIEW"}
        )
    assert response.status_code == 401


def test_viewer_patch_is_forbidden_and_unaudited(app_client, auth_setup) -> None:
    report = _create(app_client)
    response = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"status": "IN_REVIEW"},
        headers=headers_for(auth_setup, UserRole.VIEWER),
    )
    assert response.status_code == 403
    assert _update_audits(app_client, report["id"]) == []


def test_inactive_writer_patch_is_forbidden(app_client, auth_setup) -> None:
    report = _create(app_client)
    assessor = auth_setup.users[UserRole.ASSESSOR]
    auth_setup.service.update_user(
        assessor.user_id, UserUpdate(is_active=False), "admin-actor"
    )
    response = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"status": "IN_REVIEW"},
        headers=headers_for(auth_setup, UserRole.ASSESSOR),
    )
    assert response.status_code == 403


def test_authorized_writer_patch_succeeds(app_client, auth_setup) -> None:
    report = _create(app_client)
    response = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"status": "IN_REVIEW"},
        headers=headers_for(auth_setup, UserRole.ASSESSOR),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IN_REVIEW"


def test_patch_actor_comes_from_token_not_body(app_client, auth_setup) -> None:
    report = _create(app_client)
    assessor = auth_setup.users[UserRole.ASSESSOR]
    response = app_client.patch(
        f"/api/reports/{report['id']}",
        json={
            "status": "IN_REVIEW",
            "actor_id": "santa-claus",
            "actor": "santa-claus",
            "reviewer_id": "santa-claus",
        },
        headers=headers_for(auth_setup, UserRole.ASSESSOR),
    )
    assert response.status_code == 200
    audits = _update_audits(app_client, report["id"])
    assert len(audits) == 1
    assert audits[0]["actor_id"] == assessor.user_id
    assert audits[0]["actor_id"] != "santa-claus"


# ---------------------------------------------------------------------------
# 4. Original evidence is immutable
# ---------------------------------------------------------------------------


def test_patch_original_text_is_rejected(app_client) -> None:
    report = _create(app_client)
    response = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"original_text": "forged evidence"},
    )
    assert response.status_code == 422

    fetched = app_client.get(f"/api/reports/{report['id']}").json()
    assert fetched["original_text"] == report["original_text"]
    assert fetched["original_extraction"] == report["original_extraction"]
    assert fetched["evidence"] == report["evidence"]
    assert _update_audits(app_client, report["id"]) == []


def test_patch_cannot_forge_original_extraction(app_client) -> None:
    report = _create(app_client)
    response = app_client.patch(
        f"/api/reports/{report['id']}",
        json={
            "original_extraction": {"hacked": True},
            "verification_status": "VERIFIED",
            "severity": "CRITICAL",
        },
    )
    assert response.status_code == 200
    fetched = app_client.get(f"/api/reports/{report['id']}").json()
    assert "hacked" not in fetched["original_extraction"]
    assert fetched["original_extraction"] == report["original_extraction"]
    assert fetched["verification_status"] == "UNVERIFIED"
    # The editable field did change.
    assert fetched["severity"] == "CRITICAL"


def test_unrelated_editable_fields_still_update(app_client) -> None:
    report = _create(app_client)
    response = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"status": "IN_REVIEW", "location": "Kochi"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "IN_REVIEW"
    assert body["location"] == "Kochi"
    assert body["original_text"] == report["original_text"]
    assert body["evidence"] == report["evidence"]


# ---------------------------------------------------------------------------
# 5. PATCH audit trail
# ---------------------------------------------------------------------------


def test_successful_patch_creates_expected_audit(app_client, auth_setup) -> None:
    report = _create(app_client, severity="HIGH")
    assessor = auth_setup.users[UserRole.ASSESSOR]
    app_client.patch(
        f"/api/reports/{report['id']}",
        json={"severity": "CRITICAL"},
        headers=headers_for(auth_setup, UserRole.ASSESSOR),
    )
    audits = _update_audits(app_client, report["id"])
    assert len(audits) == 1
    record = audits[0]
    assert record["report_id"] == report["id"]
    assert record["actor_id"] == assessor.user_id
    assert record["old_value"] == {"severity": "HIGH"}
    assert record["new_value"] == {"severity": "CRITICAL"}
    assert record["timestamp"]


def test_rejected_patch_creates_no_success_audit(app_client) -> None:
    report = _create(app_client)
    response = app_client.patch(
        f"/api/reports/{report['id']}", json={"severity": "BOGUS"}
    )
    assert response.status_code == 422
    assert _update_audits(app_client, report["id"]) == []


def test_noop_patch_creates_no_audit(app_client) -> None:
    report = _create(app_client, severity="HIGH")
    response = app_client.patch(
        f"/api/reports/{report['id']}", json={"severity": "HIGH"}
    )
    assert response.status_code == 200
    assert _update_audits(app_client, report["id"]) == []


# ---------------------------------------------------------------------------
# 6. Priority recomputation / invalidation
# ---------------------------------------------------------------------------


def test_priority_relevant_patch_recomputes_backend_priority(app_client) -> None:
    report = _create(
        app_client,
        severity="LOW",
        affected_population=10,
        vulnerability=[],
        time_sensitivity="",
        evidence=[],
    )
    before = app_client.post(f"/api/reports/{report['id']}/priority").json()
    assert before["severity_score"] == 25.0

    app_client.patch(
        f"/api/reports/{report['id']}", json={"severity": "CRITICAL"}
    )
    after = app_client.post(f"/api/reports/{report['id']}/priority").json()
    assert after["severity_score"] == 100.0
    assert after["final_score"] > before["final_score"]


class _RecordingPriority:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def recalculate_for_report(self, report_id: str):
        self.calls.append(report_id)
        return None


class _FakePriorityStore:
    def __init__(self) -> None:
        self.saved: list[object] = []
        self.deleted: list[str] = []

    def save(self, result: object) -> None:
        self.saved.append(result)

    def delete_by_report(self, report_id: str) -> None:
        self.deleted.append(report_id)


def _seed_report(report_id: str = "r1", **overrides) -> Report:
    base = dict(
        id=report_id,
        original_text="Report r1",
        reporter="field_team_01",
        timestamp=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        location="Kozhikode",
        incident="Flood",
        severity=SeverityLevel.HIGH,
        affected_population=500,
        vulnerability=["children"],
        time_sensitivity="urgent",
        evidence=["bridge washed away"],
    )
    base.update(overrides)
    return Report(**base)


def test_unrelated_patch_does_not_recalculate_priority() -> None:
    repository = InMemoryReportRepository()
    repository.create(_seed_report())
    spy = _RecordingPriority()
    service = ReportService(
        repository, InMemoryAuditRepository(), priority_service=spy
    )

    service.update("r1", UpdateReport(location="Kochi"), actor=_ACTOR)
    assert spy.calls == []

    service.update(
        "r1", UpdateReport(severity=SeverityLevel.CRITICAL), actor=_ACTOR
    )
    assert spy.calls == ["r1"]


def test_priority_recomputed_and_saved_on_relevant_patch() -> None:
    repository = InMemoryReportRepository()
    repository.create(_seed_report())
    store = _FakePriorityStore()
    service = ReportService(
        repository,
        InMemoryAuditRepository(),
        priority_service=PriorityService(repository, result_store=store),
    )

    service.update(
        "r1", UpdateReport(severity=SeverityLevel.CRITICAL), actor=_ACTOR
    )
    assert len(store.saved) == 1
    assert store.saved[0].severity_score == 100.0
    assert store.saved[0].priority_level == priority_level_for_score(
        store.saved[0].final_score
    )


def test_priority_invalidated_when_signal_removed() -> None:
    repository = InMemoryReportRepository()
    repository.create(_seed_report())
    store = _FakePriorityStore()
    service = ReportService(
        repository,
        InMemoryAuditRepository(),
        priority_service=PriorityService(repository, result_store=store),
    )

    service.update(
        "r1",
        UpdateReport(
            severity=None,
            affected_population=None,
            vulnerability=[],
            time_sensitivity=None,
            evidence=[],
        ),
        actor=_ACTOR,
    )
    assert store.deleted == ["r1"]
    assert store.saved == []


# ---------------------------------------------------------------------------
# 7. Verification / duplicate / conflict invariants
# ---------------------------------------------------------------------------


def test_patch_preserves_verification_and_original_evidence(
    app_client, auth_setup
) -> None:
    report = _create(app_client)
    app_client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "confirmed"},
        headers=headers_for(auth_setup, UserRole.REVIEWER),
    )

    app_client.patch(
        f"/api/reports/{report['id']}", json={"severity": "CRITICAL"}
    )

    fetched = app_client.get(f"/api/reports/{report['id']}").json()
    # Editing never re-verifies a report or rewrites its evidence.
    assert fetched["verification_status"] == "VERIFIED"
    assert fetched["original_text"] == report["original_text"]
    assert fetched["original_extraction"] == report["original_extraction"]
    assert fetched["evidence"] == report["evidence"]


def test_patch_does_not_merge_or_delete_reports(app_client) -> None:
    first = _create(app_client)
    second = _create(app_client, reporter="field_team_02")

    app_client.patch(
        f"/api/reports/{first['id']}", json={"location": "Kochi"}
    )

    listing = app_client.get("/api/reports").json()
    ids = {item["id"] for item in listing}
    assert {first["id"], second["id"]} <= ids
    assert app_client.get(f"/api/reports/{second['id']}").status_code == 200
