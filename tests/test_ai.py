import json

import pytest
from fastapi.testclient import TestClient

from app.ai.client import GeminiClient
from app.ai.errors import AIConfigurationError, AIGatewayError, AIResponseError
from app.api.ai import get_ai_service
from app.main import app
from app.services.ai_service import AIService

VALID_EXTRACTION_JSON = json.dumps(
    {
        "incident": "Flood",
        "location": "Area X",
        "needs": ["WATER", "FOOD"],
        "severity": "HIGH",
        "affected_population": 500,
        "vulnerability": ["children"],
        "time_sensitivity": "needs water within 48 hours",
        "evidence": ["there is no clean drinking water"],
    }
)


class FakeAIClient:
    """AIClient stand-in that returns scripted Gemini output."""

    def __init__(
        self,
        raw: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self._raw = raw
        self._error = error
        self.calls: list[str] = []

    def generate_json(self, *, system_instruction: str, prompt: str) -> str:
        self.calls.append(prompt)
        if self._error is not None:
            raise self._error
        return self._raw or ""


@pytest.fixture()
def ai_client(auth_setup, admin_headers) -> TestClient:
    """TestClient against the real app; the AI service is injected per test.
    The client is pre-authenticated as the seeded ADMIN user."""
    with TestClient(app) as client:
        client.headers.update(admin_headers)
        yield client
    app.dependency_overrides.clear()


def _override_ai_service(client: TestClient, raw: str | None = None, error: Exception | None = None) -> None:
    service = AIService(FakeAIClient(raw=raw, error=error))
    app.dependency_overrides[get_ai_service] = lambda: service


def test_successful_gemini_request(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw=VALID_EXTRACTION_JSON)
    response = ai_client.post(
        "/api/ai/analyze",
        json={"original_text": "There is no clean drinking water in the village."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["original_text"] == "There is no clean drinking water in the village."
    assert body["extraction"]["incident"] == "Flood"
    assert body["extraction"]["needs"] == ["WATER", "FOOD"]


def test_valid_structured_response(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw=VALID_EXTRACTION_JSON)
    response = ai_client.post("/api/ai/analyze", json={"original_text": "example"})
    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert extraction["severity"] == "HIGH"
    assert extraction["affected_population"] == 500
    assert extraction["time_sensitivity"] == "needs water within 48 hours"


def test_empty_response(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw=None)
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


def test_invalid_json_response(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw="this is not json")
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


def test_pydantic_validation_failure(ai_client: TestClient) -> None:
    bad = json.dumps({"needs": ["NOT_A_CATEGORY"]})
    _override_ai_service(ai_client, raw=bad)
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


def test_gemini_api_failure(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, error=AIGatewayError("boom"))
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "unavailable" in response.json()["detail"]


def test_missing_api_key_raises_configuration_error() -> None:
    client = GeminiClient(api_key="", model="gemini-2.5-flash")
    with pytest.raises(AIConfigurationError):
        client.generate_json(system_instruction="sys", prompt="pro")


def test_missing_api_key_endpoint_returns_503(ai_client: TestClient) -> None:
    def _missing_key_service():
        return AIService(GeminiClient(api_key="", model="gemini-2.5-flash"))

    app.dependency_overrides[get_ai_service] = _missing_key_service
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_ai_response_error_is_clean(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, error=AIResponseError("bad data"))
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


def test_report_text_unchanged(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw=VALID_EXTRACTION_JSON)
    original = "No clean drinking water in the village. Preserve me exactly."
    response = ai_client.post("/api/ai/analyze", json={"original_text": original})
    assert response.status_code == 200
    assert response.json()["original_text"] == original


def test_validation_of_request_empty_text(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw=VALID_EXTRACTION_JSON)
    response = ai_client.post("/api/ai/analyze", json={"original_text": ""})
    assert response.status_code == 422


def test_endpoint_appears_in_openapi() -> None:
    paths = list(app.openapi()["paths"].keys())
    assert "/api/ai/analyze" in paths
    operations = app.openapi()["paths"]["/api/ai/analyze"]
    assert "post" in operations