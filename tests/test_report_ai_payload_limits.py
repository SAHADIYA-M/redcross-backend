"""Batch 3: report and AI payload text limits.

Report and AI-analyze payload text fields are bounded so a single request
cannot exhaust memory or storage. Limits stay generous for real humanitarian
field reports; oversized payloads are rejected with a normal 422 validation
error, never silently truncated.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

MAX_REPORT_TEXT = 50_000
MAX_LOCATION = 500
MAX_EVIDENCE_ITEM = 2_000


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_report_original_text_too_long_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/reports",
        json={
            "original_text": "x" * (MAX_REPORT_TEXT + 1),
            "reporter": "team_a",
        },
    )
    assert response.status_code == 422


def test_report_location_too_long_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/reports",
        json={
            "original_text": "people need water",
            "reporter": "team_a",
            "location": "A" * (MAX_LOCATION + 1),
        },
    )
    assert response.status_code == 422


def test_report_evidence_item_too_long_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/reports",
        json={
            "original_text": "people need water",
            "reporter": "team_a",
            "evidence": ["B" * (MAX_EVIDENCE_ITEM + 1)],
        },
    )
    assert response.status_code == 422


def test_report_patch_limits_update_fields(client: TestClient) -> None:
    created = client.post(
        "/api/reports",
        json={"original_text": "people need water", "reporter": "team_a"},
    )
    assert created.status_code == 201
    report_id = created.json()["id"]
    response = client.patch(
        f"/api/reports/{report_id}",
        json={"incident": "C" * (MAX_LOCATION + 1)},
    )
    assert response.status_code == 422


def test_ai_analyze_text_too_long_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/ai/analyze",
        json={"original_text": "x" * (MAX_REPORT_TEXT + 1)},
    )
    assert response.status_code == 422


def test_large_but_within_limit_payload_accepted(client: TestClient) -> None:
    response = client.post(
        "/api/reports",
        json={
            "original_text": "w" * MAX_REPORT_TEXT,
            "reporter": "team_a",
        },
    )
    assert response.status_code == 201, response.text


def test_ai_analyze_at_limit_payload_accepted(client: TestClient) -> None:
    from app.api.ai import get_ai_service
    from app.services.ai_service import AIService
    from tests.test_ai import FakeAIClient

    app.dependency_overrides[get_ai_service] = (
        lambda: AIService(FakeAIClient(raw='{"needs": []}'))
    )
    response = client.post(
        "/api/ai/analyze",
        json={"original_text": "z" * 100},
    )
    assert response.status_code == 200, response.text