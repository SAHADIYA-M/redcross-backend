"""Phase 4 tests: AI output validation and need classification.

Covers the required scenarios: valid output, malformed output, invalid need
categories, multiple needs, missing/uncertain information, OTHER fallback,
original report preservation, strict population validation, deterministic
backend classification and clean error handling. Uses a fake AI client so the
live Gemini API is never called.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.ai.classification import NeedClassifier
from app.ai.errors import AIGatewayError
from app.ai.schemas import AIExtraction, NeedCategory
from app.ai.validation import AIValidator
from app.api.ai import get_ai_service
from app.main import app
from app.services.ai_service import AIService

from tests.test_ai import FakeAIClient


@pytest.fixture()
def ai_client() -> TestClient:
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _override_ai_service(
    client: TestClient, raw: str | None = None, error: Exception | None = None
) -> None:
    service = AIService(FakeAIClient(raw=raw, error=error))
    app.dependency_overrides[get_ai_service] = lambda: service


WATER_REPORT = "There is no clean drinking water in the village."
CLINIC_REPORT = "The clinic has no medicines and injured people need treatment."


def _valid_json() -> str:
    return json.dumps(
        {
            "incident": "Flood",
            "location": "Area X",
            "needs": ["WATER", "FOOD"],
            "severity": "HIGH",
            "affected_population": 500,
            "vulnerability": ["children", "elderly"],
            "time_sensitivity": "needs water within 48 hours",
            "evidence": ["there is no clean drinking water"],
        }
    )


def test_backend_controls_need_categories(ai_client: TestClient) -> None:
    """Invalid category from the AI is rejected (not silently accepted)."""
    bad = json.dumps({"needs": ["CASH"]})
    _override_ai_service(ai_client, raw=bad)
    response = ai_client.post("/api/ai/analyze", json={"original_text": WATER_REPORT})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]

    for category in NeedCategory:
        AIExtraction(needs=[category.value])  # every controlled category is accepted


def test_multiple_needs_preserved(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw=_valid_json())
    response = ai_client.post("/api/ai/analyze", json={"original_text": WATER_REPORT})
    assert response.status_code == 200
    needs = response.json()["extraction"]["needs"]
    assert "WATER" in needs
    assert "FOOD" in needs


def test_other_when_no_clear_need(ai_client: TestClient) -> None:
    """A report with no identifiable need must resolve to OTHER."""
    empty = json.dumps({"incident": None, "needs": []})
    _override_ai_service(ai_client, raw=empty)
    response = ai_client.post(
        "/api/ai/analyze", json={"original_text": "The sky is blue and birds fly."}
    )
    assert response.status_code == 200
    assert response.json()["extraction"]["needs"] == ["OTHER"]


def test_uncertainty_is_preserved(ai_client: TestClient) -> None:
    """Missing information stays null; nothing is fabricated."""
    sparse = json.dumps({"incident": None, "location": None, "needs": ["WATER"]})
    _override_ai_service(ai_client, raw=sparse)
    response = ai_client.post("/api/ai/analyze", json={"original_text": WATER_REPORT})
    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert extraction["incident"] is None
    assert extraction["location"] is None
    assert extraction["severity"] is None
    assert extraction["affected_population"] is None


def test_invalid_population_rejected(ai_client: TestClient) -> None:
    bad = json.dumps({"needs": ["WATER"], "affected_population": -5})
    _override_ai_service(ai_client, raw=bad)
    response = ai_client.post("/api/ai/analyze", json={"original_text": WATER_REPORT})
    assert response.status_code == 502

    bad_string = json.dumps({"needs": ["WATER"], "affected_population": "many people"})
    _override_ai_service(ai_client, raw=bad_string)
    response = ai_client.post("/api/ai/analyze", json={"original_text": WATER_REPORT})
    assert response.status_code == 502


def test_original_report_preserved(ai_client: TestClient) -> None:
    original = "There is no clean drinking water in the village. Keep me exact."
    _override_ai_service(ai_client, raw=_valid_json())
    response = ai_client.post("/api/ai/analyze", json={"original_text": original})
    assert response.status_code == 200
    assert response.json()["original_text"] == original


def test_classifier_detects_water(ai_client: TestClient) -> None:
    needs = NeedClassifier().classify(WATER_REPORT)
    assert NeedCategory.WATER in needs


def test_classifier_detects_healthcare_and_items(ai_client: TestClient) -> None:
    needs = NeedClassifier().classify(CLINIC_REPORT)
    assert NeedCategory.HEALTHCARE in needs


def test_classifier_merges_with_ai_output() -> None:
    extraction = AIExtraction(needs=[NeedCategory.OTHER])
    validated = AIValidator().validate(extraction, CLINIC_REPORT)
    assert NeedCategory.HEALTHCARE in validated.needs


def test_validation_merges_and_deduplicates() -> None:
    extraction = AIExtraction(needs=[NeedCategory.WATER, NeedCategory.WATER])
    validated = AIValidator().validate(extraction, WATER_REPORT)
    assert validated.needs.count(NeedCategory.WATER) == 1
    assert validated.needs == [NeedCategory.WATER]


def test_malformed_json_from_ai(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw="not json at all")
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


def test_empty_response_from_ai(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, raw="")
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


def test_pydantic_failure_is_clean(ai_client: TestClient) -> None:
    """A structure mismatch yields an error, not a stack trace or data leak."""
    bad = json.dumps({"needs": [{"malformed": True}]})
    _override_ai_service(ai_client, raw=bad)
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]
    assert "<" not in response.json()["detail"]


def test_gemini_failure_is_clean(ai_client: TestClient) -> None:
    _override_ai_service(ai_client, error=AIGatewayError("upstream broken"))
    response = ai_client.post("/api/ai/analyze", json={"original_text": "x"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "unavailable" in detail
    assert "upstream broken" not in detail


def test_no_priority_in_output(ai_client: TestClient) -> None:
    """This phase does not compute priority; the schema must not contain it."""
    from app.schemas.ai import AnalyzeResponse

    assert "priority" not in AnalyzeResponse.model_fields["extraction"].annotation.model_fields