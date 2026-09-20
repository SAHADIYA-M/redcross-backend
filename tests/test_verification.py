"""Phase 9 tests: human verification workflow + append-only audit logging.

Covers the 20 required scenarios: GET /api/verification, every verification
action, error handling, original-evidence preservation, audit immutability,
priority recalculation and the no-database constraint.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.conflicts import get_conflict_service
from app.api.duplicates import get_duplicate_service
from app.api.priority import get_priority_service
from app.api.reports import get_report_service
from app.api.verification import get_audit_repository, get_verification_service
from app.conflicts.service import ConflictDetectionService
from app.duplicates.service import DuplicateDetectionService
from app.main import app
from app.repositories import InMemoryReportRepository
from app.repositories.in_memory_audit_repository import InMemoryAuditRepository
from app.repositories.in_memory_verification_repository import (
    InMemoryVerificationRepository,
)
from app.services.priority_service import PriorityService
from app.services.report_service import ReportService
from app.verification.service import VerificationService

BASE_TIME = "2026-09-20T10:00:00Z"


@pytest.fixture()
def client(auth_setup, admin_headers):
    """Give every test a clean, isolated in-memory storage set.

    All repositories are created fresh and shared so report creation,
    verification, audit, duplicate and conflict features all see the same
    data — exactly like the production app wiring. The client is
    pre-authenticated as the seeded ADMIN user.
    """
    report_repository = InMemoryReportRepository()
    verification_repository = InMemoryVerificationRepository()
    audit_repository = InMemoryAuditRepository()

    app.dependency_overrides[get_report_service] = (
        lambda: ReportService(report_repository)
    )
    app.dependency_overrides[get_verification_service] = (
        lambda: VerificationService(
            report_repository,
            verification_repository,
            audit_repository,
        )
    )
    app.dependency_overrides[get_audit_repository] = lambda: audit_repository
    app.dependency_overrides[get_priority_service] = (
        lambda: PriorityService(report_repository)
    )
    app.dependency_overrides[get_duplicate_service] = (
        lambda: DuplicateDetectionService(report_repository)
    )
    app.dependency_overrides[get_conflict_service] = (
        lambda: ConflictDetectionService(report_repository)
    )
    with TestClient(app) as test_client:
        test_client.headers.update(admin_headers)
        yield test_client
    app.dependency_overrides.clear()


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": "People near the school have no clean drinking water",
        "reporter": "field_team_01",
        "location": "Riverside Camp",
        "incident": "Flood",
        "timestamp": BASE_TIME,
        "source": "FIELD_REPORT",
        "needs": ["WATER"],
        "severity": "HIGH",
        "affected_population": 200,
        "vulnerability": ["children"],
        "time_sensitivity": "urgent",
        "evidence": ["no clean drinking water"],
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _verify(client: TestClient, report_id: str, **body) -> dict:
    response = client.patch(f"/api/reports/{report_id}/verify", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _audit(client: TestClient, report_id: str | None = None) -> list[dict]:
    params = {"report_id": report_id} if report_id else None
    response = client.get("/api/audit", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# 1. GET /api/verification
# --------------------------------------------------------------------------


def test_get_verification_empty_queue(client: TestClient) -> None:
    response = client.get("/api/verification")
    assert response.status_code == 200
    assert response.json() == []


def test_get_verification_lists_records_and_filters(client: TestClient) -> None:
    r1 = _create(client)
    r2 = _create(client)
    _verify(client, r1["id"], action="APPROVE", reason="confirmed")
    _verify(client, r1["id"], action="MARK_UNCERTAIN", reason="unclear")
    _verify(client, r2["id"], action="REJECT", reason="false lead")

    assert len(client.get("/api/verification").json()) == 3

    by_report = client.get(
        "/api/verification", params={"report_id": r1["id"]}
    ).json()
    assert len(by_report) == 2

    by_status = client.get(
        "/api/verification", params={"verification_status": "UNCERTAIN"}
    ).json()
    assert len(by_status) == 1
    assert by_status[0]["report_id"] == r1["id"]

    by_action = client.get(
        "/api/verification", params={"action": "REJECT"}
    ).json()
    assert len(by_action) == 1
    assert by_action[0]["report_id"] == r2["id"]

    missing = client.get(
        "/api/verification", params={"report_id": "does-not-exist"}
    ).json()
    assert missing == []


# --------------------------------------------------------------------------
# 2. APPROVE
# --------------------------------------------------------------------------


def test_approve_marks_verified_and_records(client: TestClient) -> None:
    report = _create(client)
    assert report["verification_status"] == "UNVERIFIED"

    result = _verify(
        client,
        report["id"],
        action="APPROVE",
        reason="Confirmed by field coordinator",
    )
    assert result["report"]["verification_status"] == "VERIFIED"
    vr = result["verification"]
    assert vr["action"] == "APPROVE"
    assert vr["report_id"] == report["id"]
    assert vr["previous_status"] == "UNVERIFIED"
    assert vr["new_status"] == "VERIFIED"
    assert vr["reason"] == "Confirmed by field coordinator"
    assert vr["changes"] == {}
    assert vr["timestamp"]


# --------------------------------------------------------------------------
# 3. EDIT
# --------------------------------------------------------------------------


def test_edit_changes_value_and_keeps_trace(client: TestClient) -> None:
    report = _create(client)  # affected_population = 200 (AI)

    result = _verify(
        client,
        report["id"],
        action="EDIT",
        reason="Field coordinator corrected population estimate",
        edits={"affected_population": 120},
    )
    assert result["report"]["affected_population"] == 120
    assert result["report"]["verification_status"] == "VERIFIED"

    change = result["verification"]["changes"]["affected_population"]
    assert change["old"] == 200
    assert change["new"] == 120


def test_edit_multiple_fields(client: TestClient) -> None:
    report = _create(client, location="Area X")
    result = _verify(
        client,
        report["id"],
        action="EDIT",
        edits={"location": "Government High School", "incident": "Storm"},
        reason="corrected",
    )
    assert result["report"]["location"] == "Government High School"
    assert result["report"]["incident"] == "Storm"
    changes = result["verification"]["changes"]
    assert set(changes) == {"location", "incident"}


def test_edit_requires_edits(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "EDIT", "reason": "oops"},
    )
    assert response.status_code == 422


def test_edit_with_empty_edits_rejected(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "EDIT", "edits": {}},
    )
    assert response.status_code == 422


def test_edit_with_no_actual_change_rejected(client: TestClient) -> None:
    report = _create(client, affected_population=200)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "EDIT", "edits": {"affected_population": 200}},
    )
    assert response.status_code == 422
    assert "did not change any field" in response.json()["detail"]


def test_edit_rejects_unknown_field(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "EDIT", "edits": {"non_existent_field": 1}},
    )
    assert response.status_code == 422


def test_edits_not_allowed_for_non_edit_actions(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "edits": {"location": "X"}},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# 4. REJECT
# --------------------------------------------------------------------------


def test_reject_marks_rejected_and_preserves_report(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "REJECT", "reason": "Not confirmed by the team"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["verification_status"] == "REJECTED"
    assert body["report"]["original_text"] == report["original_text"]
    assert body["report"]["evidence"] == report["evidence"]
    assert body["report"]["affected_population"] == report["affected_population"]


def test_reject_requires_reason(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "REJECT"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# 5. MARK_UNCERTAIN
# --------------------------------------------------------------------------


def test_mark_uncertain(client: TestClient) -> None:
    report = _create(client)
    result = _verify(
        client,
        report["id"],
        action="MARK_UNCERTAIN",
        reason="Ambiguous evidence",
    )
    assert result["report"]["verification_status"] == "UNCERTAIN"
    vr = result["verification"]
    assert vr["action"] == "MARK_UNCERTAIN"
    assert vr["previous_status"] == "UNVERIFIED"
    assert vr["new_status"] == "UNCERTAIN"
    assert vr["reason"] == "Ambiguous evidence"


def test_uncertainty_remains_uncertainty(client: TestClient) -> None:
    report = _create(client)
    first = _verify(client, report["id"], action="MARK_UNCERTAIN", reason="unclear")
    assert first["report"]["verification_status"] == "UNCERTAIN"

    second = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "MARK_UNCERTAIN", "reason": "still unclear"},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["report"]["verification_status"] == "UNCERTAIN"
    assert body["verification"]["previous_status"] == "UNCERTAIN"
    assert body["verification"]["new_status"] == "UNCERTAIN"
    # underlying evidence and original AI output are untouched
    assert body["report"]["evidence"] == report["evidence"]
    assert body["report"]["original_extraction"]["affected_population"] == 200


# --------------------------------------------------------------------------
# 6. REQUEST_ASSESSMENT
# --------------------------------------------------------------------------


def test_request_assessment(client: TestClient, auth_setup) -> None:
    from app.models.user import UserRole

    admin_user = auth_setup.users[UserRole.ADMIN]
    report = _create(client)
    response = client.post(
        f"/api/reports/{report['id']}/request-assessment",
        json={
            "reason": (
                "Location is ambiguous and affected population requires "
                "field verification"
            ),
            "reviewer_id": "analyst_1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["verification_status"] == "ASSESSMENT_REQUESTED"
    vr = body["verification"]
    assert vr["action"] == "REQUEST_ASSESSMENT"
    assert vr["previous_status"] == "UNVERIFIED"
    assert vr["new_status"] == "ASSESSMENT_REQUESTED"
    # The authenticated reviewer is authoritative; a spoofed reviewer_id is
    # ignored (Phase 13).
    assert vr["reviewer_id"] == admin_user.user_id
    assert vr["reason"].startswith("Location is ambiguous")
    audit = _audit(client, report["id"])
    assert audit[0]["action"] == "REQUEST_ASSESSMENT"


def test_request_assessment_is_not_verification(client: TestClient) -> None:
    report = _create(client)
    client.post(
        f"/api/reports/{report['id']}/request-assessment",
        json={
            "reason": "needs field verification",
            "reviewer_id": "analyst_1",
        },
    )
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["verification_status"] == "ASSESSMENT_REQUESTED"
    assert stored["verification_status"] != "VERIFIED"
    assert stored["original_text"] == report["original_text"]
    assert stored["evidence"] == report["evidence"]


def test_request_assessment_requires_reason(client: TestClient) -> None:
    report = _create(client)
    response = client.post(
        f"/api/reports/{report['id']}/request-assessment",
        json={},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# 7. Nonexistent report
# --------------------------------------------------------------------------


def test_verify_nonexistent_report(client: TestClient) -> None:
    response = client.patch(
        "/api/reports/does-not-exist/verify",
        json={"action": "APPROVE", "reason": "x"},
    )
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_request_assessment_nonexistent_report(client: TestClient) -> None:
    response = client.post(
        "/api/reports/does-not-exist/request-assessment",
        json={"reason": "x"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# 8. Invalid action
# --------------------------------------------------------------------------


def test_invalid_action_rejected(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE_IT"},
    )
    assert response.status_code == 422


def test_request_assessment_via_verify_rejected(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "REQUEST_ASSESSMENT", "reason": "x"},
    )
    assert response.status_code == 422


def test_invalid_transition_returns_409(client: TestClient) -> None:
    report = _create(client)
    _verify(client, report["id"], action="APPROVE", reason="ok")
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "again"},
    )
    assert response.status_code == 409
    assert "from status VERIFIED" in response.json()["detail"]

    # overturning a previous approval with REJECT is allowed, but a second
    # REJECT on the now-rejected report is an invalid transition
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "REJECT", "reason": "withdrawn"},
    )
    assert response.status_code == 200
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "REJECT", "reason": "already rejected"},
    )
    assert response.status_code == 409
    assert "from status REJECTED" in response.json()["detail"]


# --------------------------------------------------------------------------
# 9. Original report text remains unchanged
# --------------------------------------------------------------------------


def test_original_report_text_never_changes(client: TestClient) -> None:
    report = _create(
        client,
        original_text="People near the school have no clean water.",
    )
    _verify(client, report["id"], action="APPROVE", reason="ok")
    _verify(
        client,
        report["id"],
        action="EDIT",
        reason="correct location",
        edits={"location": "Government High School"},
    )
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["original_text"] == "People near the school have no clean water."
    assert stored["reporter"] == report["reporter"]
    assert stored["timestamp"] == report["timestamp"]
    assert stored["source"] == report["source"]


# --------------------------------------------------------------------------
# 10. Original evidence remains preserved
# --------------------------------------------------------------------------


def test_original_evidence_preserved_after_edit(client: TestClient) -> None:
    evidence = ["no clean drinking water", "school closed"]
    report = _create(client, evidence=evidence)
    _verify(
        client,
        report["id"],
        action="EDIT",
        reason="field check",
        edits={"affected_population": 500},
    )
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["evidence"] == evidence


def test_edit_cannot_touch_original_evidence(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "EDIT", "edits": {"evidence": ["forged quote"]}},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# 11. Verification status changes correctly
# --------------------------------------------------------------------------


def test_verification_status_transitions(client: TestClient) -> None:
    report = _create(client)
    assert report["verification_status"] == "UNVERIFIED"

    _verify(client, report["id"], action="APPROVE", reason="ok")
    assert client.get(f"/api/reports/{report['id']}").json()[
        "verification_status"
    ] == "VERIFIED"

    _verify(client, report["id"], action="MARK_UNCERTAIN", reason="doubt")
    assert client.get(f"/api/reports/{report['id']}").json()[
        "verification_status"
    ] == "UNCERTAIN"

    _verify(client, report["id"], action="EDIT", edits={"location": "New Site"}, reason="fix")
    assert client.get(f"/api/reports/{report['id']}").json()[
        "verification_status"
    ] == "VERIFIED"

    _verify(client, report["id"], action="REJECT", reason="false")
    assert client.get(f"/api/reports/{report['id']}").json()[
        "verification_status"
    ] == "REJECTED"

    # rejected cannot be approved or edited without going through the
    # request-assessment path
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "x"},
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------
# 12. Audit record is created
# --------------------------------------------------------------------------


def test_audit_record_created(client: TestClient, auth_setup) -> None:
    from app.models.user import UserRole

    admin_user = auth_setup.users[UserRole.ADMIN]
    report = _create(client)
    _verify(client, report["id"], action="APPROVE", reason="confirmed")
    records = _audit(client)
    assert len(records) == 1
    record = records[0]
    assert record["report_id"] == report["id"]
    assert record["action"] == "APPROVE"
    # Phase 13: the authenticated reviewer is recorded as the actor.
    assert record["actor_id"] == admin_user.user_id
    assert record["reason"] == "confirmed"
    assert record["old_value"] == {"verification_status": "UNVERIFIED"}
    assert record["new_value"] == {"verification_status": "VERIFIED"}
    assert record["timestamp"]
    assert record["audit_id"]


def test_audit_records_reviewer_id(client: TestClient, auth_setup) -> None:
    from app.models.user import UserRole

    admin_user = auth_setup.users[UserRole.ADMIN]
    report = _create(client)
    _verify(client, report["id"], action="APPROVE", reason="ok", reviewer_id="alice")
    # The authenticated reviewer is authoritative; "alice" is never recorded.
    assert _audit(client)[0]["actor_id"] == admin_user.user_id


# --------------------------------------------------------------------------
# 13. Audit contains old/new values for EDIT
# --------------------------------------------------------------------------


def test_audit_contains_edit_old_new_values(client: TestClient) -> None:
    report = _create(client)  # affected_population = 200
    _verify(
        client,
        report["id"],
        action="EDIT",
        reason="Field coordinator corrected population estimate",
        edits={"affected_population": 120},
    )
    record = _audit(client)[0]
    assert record["action"] == "EDIT"
    assert record["old_value"] == {"affected_population": 200}
    assert record["new_value"] == {"affected_population": 120}
    assert record["reason"] == "Field coordinator corrected population estimate"


# --------------------------------------------------------------------------
# 14. Audit records cannot be modified through an API
# --------------------------------------------------------------------------


def test_audit_records_cannot_be_modified(client: TestClient) -> None:
    report = _create(client)
    _verify(client, report["id"], action="APPROVE", reason="ok")

    # No update/delete route exists for audit records
    for method in ("patch", "delete", "put"):
        response = getattr(client, method)(f"/api/audit/{report['id']}")
        assert response.status_code == 404, method

    # The only exposed operation on the collection is GET (read-only)
    schema = app.openapi()
    assert list(schema["paths"]["/api/audit"].keys()) == ["get"]


# --------------------------------------------------------------------------
# 15. Multiple verification actions create separate audit records
# --------------------------------------------------------------------------


def test_multiple_actions_create_separate_audit_records(client: TestClient) -> None:
    report = _create(client)
    _verify(client, report["id"], action="APPROVE", reason="one")
    _verify(client, report["id"], action="MARK_UNCERTAIN", reason="two")
    _verify(
        client,
        report["id"],
        action="EDIT",
        edits={"severity": "LOW"},
        reason="three",
    )
    audit = _audit(client, report["id"])
    assert len(audit) == 3
    assert {r["action"] for r in audit} == {"APPROVE", "MARK_UNCERTAIN", "EDIT"}

    verifications = client.get(
        "/api/verification", params={"report_id": report["id"]}
    ).json()
    assert len(verifications) == 3


# --------------------------------------------------------------------------
# 16. Reviewer correction is distinguishable from AI output
# --------------------------------------------------------------------------


def test_reviewer_correction_distinguishable_from_ai_output(client: TestClient) -> None:
    report = _create(client, affected_population=200)
    assert report["original_extraction"]["affected_population"] == 200

    _verify(
        client,
        report["id"],
        action="EDIT",
        edits={"affected_population": 120},
        reason="corrected by field verification",
    )
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["affected_population"] == 120  # current human-verified value
    assert stored["original_extraction"]["affected_population"] == 200  # AI output

    audit = _audit(client)[0]
    assert audit["old_value"]["affected_population"] == 200
    assert audit["new_value"]["affected_population"] == 120


def test_ai_output_never_auto_verified(client: TestClient) -> None:
    report = _create(client, severity="CRITICAL", affected_population=5000)
    stored = client.get(f"/api/reports/{report['id']}").json()
    assert stored["verification_status"] == "UNVERIFIED"


# --------------------------------------------------------------------------
# 17. Uncertainty remains uncertainty
# --------------------------------------------------------------------------
# (covered by test_uncertainty_remains_uncertainty above)


# --------------------------------------------------------------------------
# 18. Duplicate/conflict relationships remain intact
# --------------------------------------------------------------------------


def test_duplicates_and_conflicts_intact_after_verification(client: TestClient) -> None:
    report_a = _create(
        client,
        original_text="500 families need clean drinking water after flooding",
        affected_population=20,
        severity="HIGH",
        vulnerability=["children", "elderly"],
    )
    report_b = _create(
        client,
        original_text="Around 500 families need clean drinking water after the flood",
        affected_population=3,
        severity="LOW",
        timestamp="2026-09-20T12:00:00Z",
        vulnerability=["children", "elderly"],
    )

    dup_before = client.post(f"/api/reports/{report_a['id']}/duplicates").json()
    conflict_before = client.post(f"/api/reports/{report_a['id']}/conflicts").json()
    assert any(
        p["related_report_id"] == report_b["id"]
        for p in dup_before["potential_duplicates"]
    )
    assert any(
        p["related_report_id"] == report_b["id"]
        for p in conflict_before["potential_conflicts"]
    )

    _verify(client, report_a["id"], action="APPROVE", reason="ok")

    assert client.post(f"/api/reports/{report_a['id']}/duplicates").json() == dup_before
    assert client.post(f"/api/reports/{report_a['id']}/conflicts").json() == conflict_before

    all_reports = client.get("/api/reports").json()
    assert len(all_reports) == 2  # no merge, no deletion
    assert client.get(f"/api/reports/{report_a['id']}").status_code == 200
    assert client.get(f"/api/reports/{report_b['id']}").status_code == 200


# --------------------------------------------------------------------------
# 19. Priority is recalculated/invalidated correctly after an edit
# --------------------------------------------------------------------------


def test_priority_recalculated_after_editing_priority_input(client: TestClient) -> None:
    report = _create(
        client,
        affected_population=2000,
        severity="CRITICAL",
        evidence=["quote"],
    )
    before = client.post(f"/api/reports/{report['id']}/priority").json()
    assert before["affected_population_score"] == 100.0
    assert before["priority_level"] == "HIGH"

    result = _verify(
        client,
        report["id"],
        action="EDIT",
        reason="population corrected by field check",
        edits={"affected_population": 120},
    )
    priority = result["priority"]
    assert priority is not None
    assert priority["affected_population_score"] == 50.0  # 100-499 band
    assert priority["source_values"]["affected_population"] == 120
    # the edited input changes the derived result: 2000 -> 120 lowers the score
    assert priority["final_score"] == 69.0
    assert priority["priority_level"] == "MEDIUM"
    assert priority["priority_level"] != before["priority_level"]
    # deriving it again through the Phase 8 endpoint matches the verify response
    after = client.post(f"/api/reports/{report['id']}/priority").json()
    assert after["final_score"] == priority["final_score"]


def test_priority_invalidated_when_no_usable_input_remains(client: TestClient) -> None:
    report = _create(
        client,
        severity="HIGH",
        affected_population=2000,
        vulnerability=[],
        time_sensitivity=None,
        evidence=[],
    )
    assert client.post(f"/api/reports/{report['id']}/priority").status_code == 200

    result = _verify(
        client,
        report["id"],
        action="EDIT",
        edits={"severity": None, "affected_population": None},
        reason="claims could not be confirmed",
    )
    assert result["priority"] is None  # invalidated, not forced

    response = client.post(f"/api/reports/{report['id']}/priority")
    assert response.status_code == 422
    assert "no usable priority information" in response.json()["detail"]


def test_reviewer_cannot_force_priority_score(client: TestClient) -> None:
    report = _create(client)
    response = client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "x", "priority": {"final_score": 99}},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# 20. No database required for tests
# --------------------------------------------------------------------------


def test_no_database_required(client: TestClient) -> None:
    """The whole workflow runs on in-memory repositories, no DB or Gemini.

    The verification is deterministic and needs no external services:
    create -> verify -> audit -> priority, all against in-memory storage.
    """
    report = _create(client)
    result = _verify(client, report["id"], action="APPROVE", reason="ok")
    assert result["report"]["id"] == report["id"]
    assert _audit(client)[0]["report_id"] == report["id"]
    assert client.get("/api/reports").status_code == 200


# --------------------------------------------------------------------------
# OpenAPI documentation
# --------------------------------------------------------------------------


def test_phase9_endpoints_in_openapi(client: TestClient) -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/reports/{report_id}/verify" in paths
    assert "/api/reports/{report_id}/request-assessment" in paths
    assert "/api/verification" in paths
    assert "/api/audit" in paths
    assert "patch" in paths["/api/reports/{report_id}/verify"]
    assert "post" in paths["/api/reports/{report_id}/request-assessment"]
    assert "get" in paths["/api/verification"]
    assert "VerificationStatus" in schema["components"]["schemas"]
    assert "VerificationAction" in schema["components"]["schemas"]
    assert "AuditRecord" in schema["components"]["schemas"]