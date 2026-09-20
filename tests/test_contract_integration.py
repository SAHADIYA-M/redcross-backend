"""Phase 14 contract-level integration tests.

Guards the API surface that front-end clients actually depend on: exactly
the intended OpenAPI path set, the bearer security scheme binding, the
unified error-JSON shapes for the whole backend, and CORS behaviour. These
hold across features regardless of service internals.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

PUBLIC_OPERATIONS = {
    ("/", "get"),
    ("/health", "get"),
    ("/api/auth/register", "post"),
    ("/api/auth/login", "post"),
}

EXPECTED_PATHS = {
    "/",
    "/health",
    "/api/ai/analyze",
    "/api/analytics/response-coverage",
    "/api/audit",
    "/api/auth/login",
    "/api/auth/me",
    "/api/auth/register",
    "/api/locations/geocode",
    "/api/map/information-gaps",
    "/api/map/reports",
    "/api/map/responses",
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


def _protected_operations() -> list[tuple[str, str]]:
    schema = app.openapi()
    operations: list[tuple[str, str]] = []
    for path, methods in schema["paths"].items():
        for method in methods:
            if (path, method) not in PUBLIC_OPERATIONS:
                operations.append((path, method))
    return operations


def _fake_id() -> str:
    return uuid.uuid4().hex


def _body_for(path: str, method: str) -> dict | None:
    """Valid minimal bodies so only the auth/role check decides the status."""
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
    """The whole backend contract stays 25 paths - freezing the surface."""
    schema = app.openapi()
    assert set(schema["paths"].keys()) == EXPECTED_PATHS
    assert schema["info"]["title"] == app.title
    assert schema["openapi"].startswith("3.")
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }


def test_only_public_operations_lack_bearer_security() -> None:
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        for method in methods:
            op = schema["paths"][path][method]
            if (path, method) in PUBLIC_OPERATIONS:
                assert "security" not in op or not op["security"]
            else:
                assert op.get("security") == [{"HTTPBearer": []}], (
                    path,
                    method,
                )


def test_public_surface_answers_without_authentication() -> None:
    client = _plain_client()
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    registered = client.post(
        "/api/auth/register",
        json={"username": "volunteer_9", "password": "s3cret-pass"},
    )
    assert registered.status_code == 201


@pytest.mark.parametrize(
    "path,method",
    [(p, m) for p, m in _protected_operations()],
)
def test_every_protected_operation_requires_a_bearer_token(path, method) -> None:
    client = _plain_client()
    url = path.replace("{report_id}", _fake_id()).replace(
        "{response_id}", _fake_id()
    ).replace("{user_id}", _fake_id())
    response = client.request(method, url, json=_body_for(path, method))
    assert response.status_code == 401


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
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin")
    assert "POST" in response.headers.get("access-control-allow-methods", "")