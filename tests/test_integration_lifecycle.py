"""Phase 14 end-to-end lifecycle integration tests.

Walks one disaster scenario through EVERY feature of the backend on shared
storage: report creation (auth) -> AI analysis (mocked) -> location geocoding
(offline stub) -> priority -> duplicates/conflicts -> human verification ->
response activities -> response coverage -> search -> map -> information gaps
-> audit trail -> user management. Each test asserts cross-feature
consistency (e.g. a verification EDIT recalculates the priority that search
and the map expose), which the per-feature suites cannot see.
"""

from fastapi.testclient import TestClient


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "original_text": (
            "About 500 families near the Kozhikode beach have no clean "
            "drinking water after the flood. Schools are closed."
        ),
        "reporter": "field_team_01",
        "location": "kozhikode beach",
        "source": "FIELD_REPORT",
        "incident": "Flood",
        "needs": ["WATER", "FOOD"],
        "severity": "HIGH",
        "affected_population": 500,
        "vulnerability": ["children", "elderly"],
        "time_sensitivity": "needs water within 24 hours",
        "evidence": ["no clean drinking water since yesterday"],
    }
    payload.update(overrides)
    response = client.post("/api/reports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _priority(client: TestClient, report_id: str) -> dict:
    response = client.post(f"/api/reports/{report_id}/priority")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# 1. AI -> Report: the intake pipeline
# --------------------------------------------------------------------------


def test_ai_analysis_and_report_creation_feed_each_other(
    app_client: TestClient,
) -> None:
    """The AI pipeline (mocked) and report intake agree on the same claims."""
    ai = app_client.post(
        "/api/ai/analyze",
        json={
            "original_text": (
                "About 500 families near the Kozhikode beach have no clean "
                "drinking water after the flood."
            )
        },
    )
    assert ai.status_code == 200
    extraction = ai.json()["extraction"]
    assert extraction["location"] == "kozhikode beach"
    # The AI NEVER decides the priority; there is no priority field in its
    # output contract.
    assert "priority" not in extraction
    assert "final_score" not in extraction

    report = _create(app_client)
    assert report["original_text"].startswith("About 500 families")
    assert report["evidence"] == ["no clean drinking water since yesterday"]
    assert report["verification_status"] == "UNVERIFIED"


# --------------------------------------------------------------------------
# 2. Location + priority + duplicates/conflicts
# --------------------------------------------------------------------------


def test_geocode_priority_duplicates_conflicts_share_the_report(
    app_client: TestClient,
) -> None:
    report = _create(app_client)

    geocode = app_client.post(
        "/api/locations/geocode", json={"raw_location": "kozhikode beach"}
    )
    assert geocode.status_code == 200
    point = geocode.json()
    assert point["status"] == "CONFIRMED"
    assert point["latitude"] == 11.2588
    assert point["longitude"] == 75.7804
    assert point["source"] == "stub"

    priority = _priority(app_client, report["id"])
    assert priority["final_score"] == 74.0
    assert priority["priority_level"] == "HIGH"
    assert priority["calculation_version"] == "1"
    assert priority["source_values"]["affected_population"] == 500

    twin = _create(app_client, reporter="field_team_02")
    duplicates = app_client.post(
        f"/api/reports/{report['id']}/duplicates"
    ).json()
    assert any(
        p["related_report_id"] == twin["id"]
        and p["similarity_score"] >= 0.85
        for p in duplicates["potential_duplicates"]
    )

    conflicts = app_client.post(
        f"/api/reports/{report['id']}/conflicts"
    ).json()
    # Identical claims are evidence, not a contradiction.
    assert conflicts["potential_conflicts"] == []

    contradictory = _create(app_client, affected_population=20, severity="LOW")
    conflicts2 = app_client.post(
        f"/api/reports/{report['id']}/conflicts"
    ).json()
    fields = {
        (claim["field"], pc["related_report_id"])
        for pc in conflicts2["potential_conflicts"]
        for claim in pc["conflicts"]
    }
    assert ("affected_population", contradictory["id"]) in fields
    assert ("severity", contradictory["id"]) in fields


# --------------------------------------------------------------------------
# 3. Human verification changes what search and the map expose
# --------------------------------------------------------------------------


def test_verification_edit_recalculates_priority_and_updates_search_map(
    app_client: TestClient,
) -> None:
    report = _create(app_client)
    assert _priority(app_client, report["id"])["priority_level"] == "HIGH"

    verify = app_client.patch(
        f"/api/reports/{report['id']}/verify",
        json={
            "action": "EDIT",
            "reason": "Field coordinator corrected the population",
            "edits": {"affected_population": 400},
        },
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["report"]["affected_population"] == 400
    assert body["report"]["original_text"].startswith("About 500 families")
    assert body["report"]["evidence"] == ["no clean drinking water since yesterday"]
    # Priority was derived by the backend from the correction, not by a client.
    assert body["priority"]["final_score"] == 67.75
    assert body["priority"]["priority_level"] == "MEDIUM"

    search = app_client.get(
        "/api/search/reports", params={"need": "WATER", "priority": "MEDIUM"}
    ).json()
    assert search["total"] == 1
    assert search["items"][0]["report_id"] == report["id"]
    assert search["items"][0]["priority_score"] == 67.75
    assert search["items"][0]["verification_status"] == "VERIFIED"

    # The same corrected priority is what the map marker carries.
    map_response = app_client.get("/api/map/reports").json()
    marker = next(
        (m for m in map_response["items"] if m["report_id"] == report["id"]),
        None,
    )
    assert marker is not None
    assert marker["latitude"] == 11.2588
    assert marker["priority_level"] == "MEDIUM"
    assert marker["priority_score"] == 67.75
    assert marker["report_status"] == "RECEIVED"


# --------------------------------------------------------------------------
# 4. Response activities + coverage + cancelled semantics
# --------------------------------------------------------------------------


def test_response_coverage_reflects_reported_needs_and_cancelled_exclusion(
    app_client: TestClient,
) -> None:
    report = _create(app_client)
    # Reviewed so the operationally visible need carries verification context.
    app_client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "confirmed"},
    )

    created = app_client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "need": "WATER",
            "activity": "Delivering bottled water",
            "response_status": "PLANNED",
            "affected_population": 300,
            "location": "kozhikode beach",
            "source": "CDC_NGO",
        },
    )
    assert created.status_code == 201
    response_id = created.json()["response_id"]

    cancelled = app_client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "need": "FOOD",
            "activity": "Ration drop",
            "response_status": "CANCELLED",
            "source": "CDC_NGO",
        },
    )
    assert cancelled.status_code == 201
    cancelled_id = cancelled.json()["response_id"]

    coverage = app_client.get(
        "/api/analytics/response-coverage", params={"report_id": report["id"]}
    ).json()
    assert coverage["total"] == 2
    by_need = {item["need"]: item for item in coverage["items"]}

    water = by_need["WATER"]
    food = by_need["FOOD"]
    # Water has one non-cancelled activity reaching 300 of the reported 500.
    assert water["response_status"] == "PARTIAL_RESPONSE_RECORDED"
    assert water["response_count"] == 1
    assert water["coverage_percentage"] == 60.0
    assert water["active_response_statuses"] == ["PLANNED"]
    assert water["verification_status"] == "VERIFIED"
    assert water["priority_level"] == "HIGH"

    # The cancelled food activity is preserved for traceability but never
    # counted as coverage: RESPONSE_RECORDED stays false.
    assert food["response_status"] == "NO_RESPONSE_RECORDED"
    assert food["response_count"] == 0
    assert food["coverage_percentage"] is None
    assert food["active_response_statuses"] == []

    listing = app_client.get(
        "/api/responses", params={"report_id": report["id"]}
    ).json()
    listed_ids = {r["response_id"] for r in listing}
    assert response_id in listed_ids
    assert cancelled_id in listed_ids  # cancelled stays listable/traceable

    # A status change is audited; the supplied actor_id is kept as-is.
    update = app_client.patch(
        f"/api/responses/{response_id}",
        json={"response_status": "IN_PROGRESS", "reason": "kicked off", "actor_id": "spoof"},
    )
    assert update.status_code == 200
    assert update.json()["response_status"] == "IN_PROGRESS"

    audit = app_client.get("/api/audit").json()
    response_audits = [
        r for r in audit if r["action"] == "UPDATE_RESPONSE"
    ]
    assert len(response_audits) == 1
    assert response_audits[0]["report_id"] == report["id"]
    assert response_audits[0]["old_value"] == {"response_status": "PLANNED"}
    assert response_audits[0]["new_value"] == {"response_status": "IN_PROGRESS"}
    # No authentication exists to override the body; "spoof" is preserved.
    assert response_audits[0]["actor_id"] == "spoof"

    # The in-progress activity appears on the response map with real coords.
    response_map = app_client.get("/api/map/responses").json()
    marker = next(
        (m for m in response_map["items"] if m["response_id"] == response_id),
        None,
    )
    assert marker is not None
    assert marker["latitude"] == 11.2588
    assert marker["longitude"] == 75.7804
    assert marker["response_status"] == "IN_PROGRESS"


# --------------------------------------------------------------------------
# 5. Search + information gaps: zero reports is a gap, never "no need"
# --------------------------------------------------------------------------


def test_search_and_information_gaps_never_confuse_absence_with_no_need(
    app_client: TestClient,
) -> None:
    _create(app_client)

    # The beach cell (11.25, 75.75) holds the report; the neighbouring cell
    # (11.25, 75.80) is enumerable and empty.
    gaps = app_client.get(
        "/api/map/information-gaps",
        params={
            "min_lat": 11.25,
            "max_lat": 11.30,
            "min_lon": 75.75,
            "max_lon": 75.85,
        },
    ).json()
    by_area = {area["area_id"]: area for area in gaps["areas"]}
    beach = by_area["cell:11.25:75.75"]
    empty = by_area["cell:11.25:75.8"]

    assert beach["report_count"] == 1
    assert beach["distinct_sources"] == 1
    # A single fresh, unverified, unset-location report is only a LIMITED
    # signal - never a confident verdict.
    assert beach["information_status"] == "LIMITED_INFORMATION"
    assert beach["information_gap_score"] == 54

    # An empty cell is INSUFFICIENT_INFORMATION (score 100), NOT low need.
    assert empty["report_count"] == 0
    assert empty["information_status"] == "INSUFFICIENT_INFORMATION"
    assert empty["information_gap_score"] == 100
    assert any(
        "No reports available" in reason for reason in empty["reasons"]
    )

    # Search for a need that exists returns the report; a non-existent need
    # returns empty items with total 0 - never a fabricated "no need" story.
    hit = app_client.get("/api/search/reports", params={"need": "WATER"}).json()
    assert hit["total"] == 1
    miss = app_client.get("/api/search/reports", params={"need": "SHELTER"}).json()
    assert miss["items"] == []
    assert miss["total"] == 0


# --------------------------------------------------------------------------
# 6. Traceability: audit + verification history across the whole flow
# --------------------------------------------------------------------------


def test_audit_trail_is_append_only_and_covers_the_whole_flow(
    app_client: TestClient, storage_repos
) -> None:
    report = _create(app_client)
    response = app_client.post(
        f"/api/reports/{report['id']}/request-assessment",
        json={"reason": "population needs field confirmation"},
    )
    assert response.status_code == 200

    audit = app_client.get("/api/audit", params={"report_id": report["id"]}).json()
    assert [r["action"] for r in audit] == ["REQUEST_ASSESSMENT"]
    assert audit[0]["old_value"] == {"verification_status": "UNVERIFIED"}
    assert audit[0]["new_value"] == {"verification_status": "ASSESSMENT_REQUESTED"}

    verified = app_client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "confirmed"},
    ).json()
    audit = app_client.get("/api/audit", params={"report_id": report["id"]}).json()
    assert [r["action"] for r in audit] == ["APPROVE", "REQUEST_ASSESSMENT"]

    # Verification history is queryable by report, status and action.
    history = app_client.get(
        "/api/verification", params={"report_id": report["id"]}
    ).json()
    assert len(history) == 2
    assert history[0]["new_status"] == "VERIFIED"

    # The audit repository interface exposes no update/delete.
    assert not hasattr(storage_repos.audit, "update")
    assert not hasattr(storage_repos.audit, "delete")

    # Audit immutability at the API level too: no write routes exist.
    schema = app_client.app.openapi()
    assert list(schema["paths"]["/api/audit"].keys()) == ["get"]


# --------------------------------------------------------------------------
# 7. User management
# --------------------------------------------------------------------------


def test_user_management_is_open(
    app_client: TestClient,
) -> None:
    assert app_client.get("/api/users").status_code == 200

    # Patching a nonexistent user is an open call resolving to a clean 404.
    missing = app_client.patch(
        "/api/users/does-not-exist",
        json={"is_active": False},
    )
    assert missing.status_code == 404