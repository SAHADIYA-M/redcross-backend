"""AI service retry tests.

Verifies the audit fix that added bounded retries for transient AI gateway
failures while NEVER retrying structural failures (empty/malformed output),
because a duplicated call would just reproduce the same unusable result.
"""

import json

import pytest

from app.ai.errors import AIGatewayError, AIResponseError
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


class FlakyClient:
    """AIClient stand-in that raises for the first ``failures`` attempts."""

    def __init__(
        self,
        *,
        failures: int,
        error: Exception = AIGatewayError("upstream down"),
        raw: str = VALID_EXTRACTION_JSON,
    ) -> None:
        self._failures = failures
        self._error = error
        self._raw = raw
        self.calls = 0

    def generate_json(self, *, system_instruction: str, prompt: str) -> str:
        self.calls += 1
        if self.calls <= self._failures:
            raise self._error
        return self._raw


def test_transient_failure_is_retried_and_recovers() -> None:
    client = FlakyClient(failures=2)
    service = AIService(client, max_retries=2, retry_backoff_seconds=0.0)

    extraction = service.analyze("no clean drinking water")

    assert client.calls == 3
    assert extraction.severity.value == "HIGH"


def test_exhausted_retries_re_raise_gateway_error() -> None:
    client = FlakyClient(failures=99)
    service = AIService(client, max_retries=2, retry_backoff_seconds=0.0)

    with pytest.raises(AIGatewayError):
        service.analyze("no clean drinking water")
    assert client.calls == 3


def test_no_retries_when_configured_off() -> None:
    client = FlakyClient(failures=1)
    service = AIService(client, max_retries=0, retry_backoff_seconds=0.0)

    with pytest.raises(AIGatewayError):
        service.analyze("no clean drinking water")
    assert client.calls == 1


def test_structural_failure_is_never_retried() -> None:
    client = FlakyClient(failures=1, error=AIResponseError("malformed output"))
    service = AIService(client, max_retries=3, retry_backoff_seconds=0.0)

    with pytest.raises(AIResponseError):
        service.analyze("no clean drinking water")
    assert client.calls == 1