"""Batch 3: Gemini extraction output is validated strictly.

Over-limit or structurally invalid AI output must be REJECTED (502 invalid
response) - never silently truncated, silently clamped, or corrected into
facts the model did not state. Post-strip length checks catch values that
would otherwise sail past field max_length padded with whitespace.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.ai import get_ai_service
from app.main import app
from app.services.ai_service import AIService
from tests.test_ai import FakeAIClient


@pytest.fixture()
def ai_client(auth_setup, admin_headers) -> TestClient:
    with TestClient(app) as client:
        client.headers.update(admin_headers)
        yield client
    app.dependency_overrides.clear()


def _analyze(client: TestClient, raw: dict | str) -> int:
    json_text = raw if isinstance(raw, str) else json.dumps(raw)
    service = AIService(FakeAIClient(raw=json_text))
    app.dependency_overrides[get_ai_service] = lambda: service
    response = client.post("/api/ai/analyze", json={"original_text": "help"})
    return response.status_code


def _item_too_long(size: int) -> str:
    return "A" * size


def test_location_over_limit_rejected(ai_client: TestClient) -> None:
    assert _analyze(ai_client, {"location": _item_too_long(501)}) == 502


def test_location_within_limit_accepted(ai_client: TestClient) -> None:
    assert _analyze(ai_client, {"location": "A" * 500}) == 200


def test_incident_over_limit_rejected(ai_client: TestClient) -> None:
    assert _analyze(ai_client, {"incident": _item_too_long(501)}) == 502


def test_time_sensitivity_over_limit_rejected(ai_client: TestClient) -> None:
    assert _analyze(ai_client, {"time_sensitivity": _item_too_long(1001)}) == 502


def test_affected_population_over_limit_rejected(ai_client: TestClient) -> None:
    assert _analyze(ai_client, {"affected_population": 10 ** 12}) == 502


def test_needs_over_limit_rejected(ai_client: TestClient) -> None:
    needs = ["WATER"] * 12
    assert _analyze(ai_client, {"needs": needs}) == 502


def test_vulnerability_item_whitespace_padded_over_limit_rejected(
    ai_client: TestClient,
) -> None:
    value = " " + _item_too_long(2001) + " "
    assert _analyze(ai_client, {"vulnerability": [value]}) == 502


def test_evidence_item_over_limit_rejected(ai_client: TestClient) -> None:
    assert _analyze(ai_client, {"evidence": [_item_too_long(2001)]}) == 502


def test_evidence_item_within_limit_accepted(ai_client: TestClient) -> None:
    assert _analyze(ai_client, {"evidence": ["A" * 2000]}) == 200


def test_valid_full_extraction_accepted(ai_client: TestClient) -> None:
    payload = {
        "incident": "Flood",
        "location": "Kozhikode district",
        "needs": ["WATER", "FOOD", "SHELTER"],
        "severity": "HIGH",
        "affected_population": 1500,
        "vulnerability": ["children", "elderly"],
        "time_sensitivity": "needs clean water within 48 hours",
        "evidence": ["wells are flooded", "no clean drinking water"],
    }
    assert _analyze(ai_client, payload) == 200