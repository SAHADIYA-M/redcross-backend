"""Phase 14 preservation guarantees.

The original evidence is the most valuable thing in the system, so it must
survive every later correction:
- original_text/evidence/reporter/source never change across verification
  actions or report PATCHes (verified through the live API);
- the immutable AI-extraction snapshot persisted at creation is never
  overwritten by a report update or a human EDIT (verified at the service +
  repository layer, since the snapshot is internal).
"""

from app.repositories import (
    InMemoryVerificationRepository,
)
from app.schemas.report import CreateReport, UpdateReport
from app.schemas.verification import VerifyRequest
from app.services.report_service import ReportService
from app.verification.schemas import VerificationAction, VerificationEdits
from app.verification.service import VerificationService


def _create_report(client) -> dict:
    response = client.post(
        "/api/reports",
        json={
            "original_text": (
                "About 500 families near the Kozhikode beach have no clean "
                "drinking water after the flood. Schools are closed."
            ),
            "reporter": "field_team_01",
            "location": "kozhikode beach",
            "source": "FIELD_REPORT",
            "needs": ["WATER", "FOOD"],
            "severity": "HIGH",
            "affected_population": 500,
            "evidence": ["no clean drinking water since yesterday"],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_verification_never_mutates_original_evidence(app_client) -> None:
    report = _create_report(app_client)
    report_id = report["id"]

    correction = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={
            "action": "EDIT",
            "reason": "population corrected",
            "edits": {"affected_population": 100},
        },
    )
    assert correction.status_code == 200
    assert correction.json()["report"]["affected_population"] == 100

    rejected = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "REJECT", "reason": "cannot be confirmed"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["report"]["verification_status"] == "REJECTED"

    final = app_client.get(f"/api/reports/{report_id}").json()
    assert final["original_text"] == report["original_text"]
    assert final["evidence"] == report["evidence"]
    assert final["reporter"] == report["reporter"]
    assert final["source"] == report["source"]


def test_report_patch_preserves_original_evidence(app_client) -> None:
    report = _create_report(app_client)

    changed = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"severity": "CRITICAL", "affected_population": 800},
    )
    assert changed.status_code == 200
    body = changed.json()
    assert body["severity"] == "CRITICAL"
    assert body["affected_population"] == 800
    assert body["original_text"] == report["original_text"]
    assert body["evidence"] == report["evidence"]


def test_original_extraction_snapshot_is_immutable(storage_repos) -> None:
    service = ReportService(storage_repos.reports)
    created = service.create(
        CreateReport(
            original_text=(
                "About 500 families near the Kozhikode beach have no clean "
                "drinking water after the flood."
            ),
            reporter="field_team_01",
            location="kozhikode beach",
            needs=["WATER"],
            affected_population=500,
            severity="HIGH",
        )
    )
    snapshot = created.original_extraction
    assert snapshot["affected_population"] == 500
    assert snapshot["needs"] == ["WATER"]

    # A report update changes the living field but never the snapshot.
    updated = service.update(
        created.id, UpdateReport(affected_population=100, severity="LOW")
    )
    assert updated.original_extraction == snapshot
    assert updated.affected_population == 100

    # A human EDIT to the interpretation also leaves the snapshot untouched.
    verifier = VerificationService(
        storage_repos.reports,
        InMemoryVerificationRepository(),
        storage_repos.audit,
    )
    verifier.verify(
        created.id,
        VerifyRequest(
            action=VerificationAction.EDIT,
            reason="field corrected",
            edits=VerificationEdits(affected_population=50, needs=["FOOD"]),
        ),
    )
    stored = storage_repos.reports.get_by_id(created.id)
    assert stored.original_extraction == snapshot
    assert stored.original_text == created.original_text
    assert stored.affected_population == 50
    assert stored.needs == ["FOOD"]