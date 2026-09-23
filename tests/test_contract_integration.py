"""Phase 14 contract-level integration tests.

Guards the API surface that front-end clients actually depend on: exactly
the intended OpenAPI path set, NO bearer security scheme anywhere (the API
is unauthenticated), the unified error-JSON shapes for the whole backend,
and CORS behaviour. These hold across features regardless of service
internals.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

EXPECTED_PATHS = {
    "/",
    "/health",
    "/api/ai/analyze",
    "/api/analytics/response-coverage",
    "/api/audit",
    "/api/clusters",
    "/api/clusters/{cluster_id}",
    "/api/fusion",
    "/api/fusion/{candidate_id}",
    "/api/fusion/{candidate_id}/resolve",
    "/api/locations/geocode",
    "/api/map/information-gaps",
    "/api/map/reports",
    "/api/map/responses",
    "/api/needs",
    "/api/priorities",
    "/api/reports",
    "/api/reports/{report_id}",
    "/api/reports/{report_id}/conflicts",
    "/api/reports/{report_id}/duplicates",
    "/api/reports/{report_id}/priority",
    "/api/reports/{report_id}/request-assessment",
    "/api/reports/{report_id}/verify",
    "/api/responses",
    "/api/responses/{response_id}",
    "/api/search/reports",
    "/api/users",
    "/api/users/{user_id}",
    "/api/verification",
}


def _plain_client() -> TestClient:
    return TestClient(app)


def _all_operations() -> list[tuple[str, str]]:
    schema = app.openapi()
    operations: list[tuple[str, str]] = []
    for path, methods in schema["paths"].items():
        for method in methods:
            operations.append((path, method))
    return operations


def _fake_id() -> str:
    return uuid.uuid4().hex


def _body_for(path: str, method: str) -> dict | None:
    """Valid minimal bodies so only correctness of the call decides."""
    if path == "/api/ai/analyze":
        return {"original_text": "people need water"}
    if path == "/api/locations/geocode":
        return {"raw_location": "kozhikode beach"}
    if path == "/api/reports" and method == "post":
        return {"original_text": "500 families need water", "reporter": "team_a"}
    if path == "/api/reports/{report_id}":
        return {"severity": "LOW"}
    if path == "/api/reports/{report_id}/verify":
        return {"action": "APPROVE", "reason": "confirmed"}
    if path == "/api/reports/{report_id}/request-assessment":
        return {"reason": "field check needed"}
    if path == "/api/responses" and method == "post":
        return {
            "report_id": _fake_id(),
            "activity": "Deliver water",
            "response_status": "PLANNED",
        }
    if path == "/api/responses/{response_id}":
        return {"response_status": "IN_PROGRESS", "reason": "kicked off"}
    if path == "/api/users/{user_id}":
        return {"is_active": False, "role": "VIEWER"}
    return None


def test_openapi_exposes_exactly_the_intended_surface() -> None:
    """The whole backend contract stays this exact path set - frozen."""
    schema = app.openapi()
    assert set(schema["paths"].keys()) == EXPECTED_PATHS
    assert schema["info"]["title"] == app.title
    assert schema["openapi"].startswith("3.")


def test_no_bearer_security_scheme_is_registered() -> None:
    """The unauthenticated API must never advertise an HTTPBearer scheme."""
    schema = app.openapi()
    assert "securitySchemes" not in schema["components"] or not schema["components"][
        "securitySchemes"
    ]
    for path, methods in schema["paths"].items():
        for method in methods:
            assert "security" not in schema["paths"][path][method], (path, method)


def test_public_surface_answers_without_authentication() -> None:
    client = _plain_client()
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    "path,method",
    [(p, m) for p, m in _all_operations()],
)
def test_every_operation_is_served_without_a_bearer_token(path, method) -> None:
    """No operation anywhere returns 401/403: the API is fully open."""
    client = _plain_client()
    url = path.replace("{report_id}", _fake_id()).replace(
        "{response_id}", _fake_id()
    ).replace("{user_id}", _fake_id())
    response = client.request(method, url, json=_body_for(path, method))
    assert response.status_code not in (401, 403), (path, method, response.status_code)


def test_not_found_errors_use_the_standard_json_shape(app_client) -> None:
    missing = app_client.get("/api/reports/does-not-exist")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Report 'does-not-exist' not found"}


def test_validation_errors_are_flat_and_json_safe(app_client) -> None:
    response = app_client.post(
        "/api/reports", json={"original_text": None}
    )
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    for item in body["detail"]:
        assert set(item) == {"loc", "msg", "type"}


def test_cors_preflight_headers(app_client) -> None:
    response = app_client.options(
        "/api/reports",
        headers={
            "Origin": "https://example.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin")
    assert "POST" in response.headers.get("access-control-allow-methods", "")