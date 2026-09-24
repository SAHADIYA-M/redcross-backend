"""Phase 14 authorization matrix integration tests (open API).

The API is unauthenticated: every operation is reachable with NO
Authorization header, and no operation ever returns 401/403. This matrix
guards against a future partial re-introduction of role guards by walking
every previously-protected operation with a bare request and asserting it is
served, not walled off by a stale dependency.
"""

import uuid

REPORT_ID = uuid.uuid4().hex
RESPONSE_ID = uuid.uuid4().hex
USER_ID = uuid.uuid4().hex
FUSION_ID = uuid.uuid4().hex

# Every formerly-protected operation. Reads resolve against random ids, so a
# data-specific 404 is the expected open outcome when the record does not
# exist; writes that reach validation may return 4xx for the dummy ids as
# long as they are NOT 401/403 (no auth wall).
OPERATIONS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/reports", None),
    ("GET", f"/api/reports/{REPORT_ID}", None),
    ("GET", "/api/verification", None),
    ("GET", "/api/audit", None),
    ("GET", "/api/search/reports", None),
    ("GET", "/api/map/reports", None),
    ("GET", "/api/map/information-gaps", None),
    ("GET", "/api/map/responses", None),
    ("GET", "/api/responses", None),
    ("GET", f"/api/responses/{RESPONSE_ID}", None),
    ("GET", "/api/analytics/response-coverage", None),
    ("POST", "/api/ai/analyze", {"original_text": "people need water"}),
    ("POST", "/api/locations/geocode", {"raw_location": "kozhikode beach"}),
    ("POST", f"/api/reports/{REPORT_ID}/duplicates", None),
    ("POST", f"/api/reports/{REPORT_ID}/conflicts", None),
    ("POST", f"/api/reports/{REPORT_ID}/priority", None),
    ("GET", "/api/fusion", None),
    ("GET", f"/api/fusion/{FUSION_ID}", None),
    ("POST", f"/api/fusion/{FUSION_ID}/resolve", {"action": "MERGED"}),
    ("POST", "/api/reports", {"original_text": "500 families need water", "reporter": "team_a"}),
    ("PATCH", f"/api/reports/{REPORT_ID}", {"severity": "LOW"}),
    ("PATCH", f"/api/reports/{REPORT_ID}/verify", {"action": "APPROVE", "reason": "confirmed"}),
    ("POST", f"/api/reports/{REPORT_ID}/request-assessment", {"reason": "field check needed"}),
    ("POST", "/api/responses", {
        "report_id": REPORT_ID,
        "activity": "Deliver water",
        "response_status": "PLANNED",
    }),
    ("PATCH", f"/api/responses/{RESPONSE_ID}", {"response_status": "IN_PROGRESS", "reason": "kicked off"}),
    ("GET", "/api/users", None),
    ("PATCH", f"/api/users/{USER_ID}", {"is_active": False}),
]


def test_no_operation_is_walled_off_by_auth(app_client) -> None:
    """Every formerly-protected operation is served WITHOUT a token."""
    for method, path, body in OPERATIONS:
        response = app_client.request(method, path, json=body)
        assert response.status_code not in (401, 403), (method, path, response.status_code)


def test_open_write_lifecycle(app_client) -> None:
    """Report → priority → verify → response → audit/users, all anonymous."""
    report = app_client.post(
        "/api/reports",
        json={
            "original_text": (
                "About 500 families near the Kozhikode beach have no clean "
                "drinking water after the flood."
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
        },
    )
    assert report.status_code == 201
    report_id = report.json()["id"]

    priority = app_client.post(f"/api/reports/{report_id}/priority")
    assert priority.status_code == 200, priority.text

    verified = app_client.patch(
        f"/api/reports/{report_id}/verify",
        json={"action": "APPROVE", "reason": "team confirmed"},
    )
    assert verified.status_code == 200, verified.text

    responded = app_client.post(
        "/api/responses",
        json={
            "report_id": report_id,
            "need": "WATER",
            "activity": "Delivering water",
            "response_status": "PLANNED",
        },
    )
    assert responded.status_code == 201, responded.text

    assert app_client.get("/api/audit").status_code == 200
    assert app_client.get("/api/users").status_code == 200