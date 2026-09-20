"""Phase 14 authorization matrix integration tests.

Every role in the system is checked against every protected operation:
- an unauthenticated request is always 401;
- an authenticated user holding a role that does not own the operation is
  always 403 (never a leak of data or a misleading 404);
- the owning role actually succeeds (2xx), proving the matrix is open, not
  just closed in the wrong places.

Identity is always the token's subject; role claims in a token are only a
convenience and the authoritative role is loaded from the user repository.
"""

import uuid

import pytest

from app.models.user import UserRole
from tests.helpers import headers_for

ALL_ROLES = set(UserRole)
REPORT_WRITER = {UserRole.ADMIN, UserRole.ASSESSOR, UserRole.REVIEWER, UserRole.RESPONDER}
REVIEWERS = {UserRole.ADMIN, UserRole.REVIEWER}
RESPONDERS = {UserRole.ADMIN, UserRole.RESPONDER}

REPORT_ID = uuid.uuid4().hex
RESPONSE_ID = uuid.uuid4().hex
USER_ID = uuid.uuid4().hex

# Every non-public operation, with the roles allowed to call it.
CASES: list[tuple[str, str, set[UserRole]]] = [
    # reads visible to any active user
    ("GET", "/api/auth/me", ALL_ROLES),
    ("GET", "/api/reports", ALL_ROLES),
    ("GET", f"/api/reports/{REPORT_ID}", ALL_ROLES),
    ("GET", "/api/verification", ALL_ROLES),
    ("GET", "/api/audit", ALL_ROLES),
    ("GET", "/api/search/reports", ALL_ROLES),
    ("GET", "/api/map/reports", ALL_ROLES),
    ("GET", "/api/map/information-gaps", ALL_ROLES),
    ("GET", "/api/map/responses", ALL_ROLES),
    ("GET", "/api/responses", ALL_ROLES),
    ("GET", f"/api/responses/{RESPONSE_ID}", ALL_ROLES),
    ("GET", "/api/analytics/response-coverage", ALL_ROLES),
    # read-like analysis endpoints visible to any active user
    ("POST", "/api/ai/analyze", ALL_ROLES),
    ("POST", "/api/locations/geocode", ALL_ROLES),
    ("POST", f"/api/reports/{REPORT_ID}/duplicates", ALL_ROLES),
    ("POST", f"/api/reports/{REPORT_ID}/conflicts", ALL_ROLES),
    ("POST", f"/api/reports/{REPORT_ID}/priority", ALL_ROLES),
    # writes restricted by role
    ("POST", "/api/reports", REPORT_WRITER),
    ("PATCH", f"/api/reports/{REPORT_ID}", REPORT_WRITER),
    ("PATCH", f"/api/reports/{REPORT_ID}/verify", REVIEWERS),
    ("POST", f"/api/reports/{REPORT_ID}/request-assessment", REVIEWERS),
    ("POST", "/api/responses", RESPONDERS),
    ("PATCH", f"/api/responses/{RESPONSE_ID}", RESPONDERS),
    ("GET", "/api/users", {UserRole.ADMIN}),
    ("PATCH", f"/api/users/{USER_ID}", {UserRole.ADMIN}),
]


def _body_for(path: str, method: str) -> dict | None:
    if path == "/api/ai/analyze":
        return {"original_text": "people need water"}
    if path == "/api/locations/geocode":
        return {"raw_location": "kozhikode beach"}
    if path == "/api/reports" and method == "post":
        return {"original_text": "500 families need water", "reporter": "team_a"}
    if path == f"/api/reports/{REPORT_ID}" and method == "patch":
        return {"severity": "LOW"}
    if path == f"/api/reports/{REPORT_ID}/verify":
        return {"action": "APPROVE", "reason": "confirmed"}
    if path == f"/api/reports/{REPORT_ID}/request-assessment":
        return {"reason": "field check needed"}
    if path == "/api/responses" and method == "post":
        return {
            "report_id": REPORT_ID,
            "activity": "Deliver water",
            "response_status": "PLANNED",
        }
    if path == f"/api/responses/{RESPONSE_ID}":
        return {"response_status": "IN_PROGRESS", "reason": "kicked off"}
    if path == f"/api/users/{USER_ID}":
        return {"is_active": False}
    return None


def test_wrong_role_is_never_granted(app_client, auth_setup) -> None:
    """For every operation, every non-owning role receives a hard 403."""
    for method, path, allowed in CASES:
        for role in sorted(ALL_ROLES, key=lambda r: r.value):
            if role in allowed:
                continue
            response = app_client.request(
                method, path, json=_body_for(path, method),
                headers=headers_for(auth_setup, role),
            )
            assert response.status_code == 403, (
                method,
                path,
                role.value,
                response.status_code,
            )


def test_any_active_role_can_read(app_client, auth_setup) -> None:
    """Reads never depend on role; the weakest role sees the same data."""
    report = _create_report(app_client)
    for role in ALL_ROLES:
        headers = headers_for(auth_setup, role)
        listings = {
            "/api/reports": (200, None),
            f"/api/reports/{report['id']}": (200, None),
            "/api/verification": (200, None),
            "/api/audit": (200, None),
            "/api/search/reports": (200, None),
            "/api/map/reports": (200, None),
            "/api/map/information-gaps": (200, None),
            "/api/map/responses": (200, None),
            "/api/responses": (200, None),
            "/api/analytics/response-coverage": (200, None),
        }
        for url, (expected, payload) in listings.items():
            response = app_client.get(url, headers=headers)
            assert response.status_code == expected, (role.value, url)

        assert app_client.get("/api/auth/me", headers=headers).status_code == 200

        analysis = [
            ("/api/ai/analyze", {"original_text": "500 families need water"}),
            ("/api/locations/geocode", {"raw_location": "kozhikode beach"}),
        ]
        for url, payload in analysis:
            response = app_client.post(url, json=payload, headers=headers)
            assert response.status_code == 200, (role.value, url)

        relation = [
            f"/api/reports/{report['id']}/duplicates",
            f"/api/reports/{report['id']}/conflicts",
            f"/api/reports/{report['id']}/priority",
        ]
        for url in relation:
            response = app_client.post(url, headers=headers)
            assert response.status_code == 200, (role.value, url)


def test_viewer_cannot_write_anything(app_client, auth_setup) -> None:
    viewer = headers_for(auth_setup, UserRole.VIEWER)
    report = _create_report(app_client)
    denied = [
        ("POST", "/api/reports", {"original_text": "x", "reporter": "y"}),
        ("PATCH", f"/api/reports/{report['id']}", {"severity": "HIGH"}),
        ("PATCH", f"/api/reports/{report['id']}/verify",
         {"action": "APPROVE", "reason": "x"}),
        ("POST", f"/api/reports/{report['id']}/request-assessment",
         {"reason": "x"}),
        ("POST", "/api/responses",
         {"report_id": report["id"], "activity": "Deliver water"}),
        ("PATCH", f"/api/users/{USER_ID}", {"is_active": False}),
        ("GET", "/api/users", None),
    ]
    for method, url, payload in denied:
        response = app_client.request(method, url, json=payload, headers=viewer)
        assert response.status_code == 403, (method, url)


def test_active_staff_write_what_they_own(app_client, auth_setup) -> None:
    from app.models.user import UserRole as R

    report = _create_report(app_client)

    # ASSESSOR owns report intake/update.
    assessed = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"notes_unused": None, "severity": "CRITICAL"},
        headers=headers_for(auth_setup, R.ASSESSOR),
    )
    assert assessed.status_code == 200

    # REVIEWER owns verification.
    reviewed = app_client.patch(
        f"/api/reports/{report['id']}/verify",
        json={"action": "APPROVE", "reason": "team confirmed"},
        headers=headers_for(auth_setup, R.REVIEWER),
    )
    assert reviewed.status_code == 200

    # RESPONDER owns response activities.
    responded = app_client.post(
        "/api/responses",
        json={
            "report_id": report["id"],
            "need": "WATER",
            "activity": "Delivering water",
            "response_status": "PLANNED",
        },
        headers=headers_for(auth_setup, R.RESPONDER),
    )
    assert responded.status_code == 201
    response_id = responded.json()["response_id"]
    updated = app_client.patch(
        f"/api/responses/{response_id}",
        json={"response_status": "IN_PROGRESS", "reason": "started"},
        headers=headers_for(auth_setup, R.RESPONDER),
    )
    assert updated.status_code == 200

    # ADMIN still owns everything incl. user management.
    users = app_client.get("/api/users", headers=headers_for(auth_setup, R.ADMIN))
    assert users.status_code == 200
    viewer = auth_setup.users[UserRole.VIEWER]
    demoted = app_client.patch(
        f"/api/users/{viewer.user_id}",
        json={"is_active": False},
        headers=headers_for(auth_setup, R.ADMIN),
    )
    assert demoted.status_code == 200


def _create_report(client) -> dict:
    response = client.post(
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
    assert response.status_code == 201
    return response.json()