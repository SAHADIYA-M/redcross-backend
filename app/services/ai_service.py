import json
import time

from pydantic import ValidationError

from app.ai.client import AIClient
from app.ai.errors import AIGatewayError, AIResponseError
from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schemas import AIExtraction
from app.ai.validation import AIValidator


def _build_prompt(report_text: str) -> str:
    return f"Report text:\n{report_text}"


class AIService:
    """Orchestrates the AI analysis pipeline.

    Pipeline: send report text to the AI client -> parse and strictly validate
    the JSON with Pydantic -> backend validation and need classification.

    Transient gateway failures (network hiccups, upstream 5xx) are retried up
    to ``max_retries`` times with a short backoff; structural failures (empty
    or malformed output) are never retried because another call would return
    the same unusable shape.

    Depends on the AIClient interface only, so the real Gemini client can be
    replaced with a fake in tests and later swapped without changing callers.
    """

    def __init__(
        self,
        client: AIClient,
        validator: AIValidator | None = None,
        *,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._client = client
        self._validator = validator or AIValidator()
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    def analyze(self, report_text: str) -> AIExtraction:
        """Return the backend-validated structured information for a report."""
        raw_json = self._generate_with_retries(report_text)
        extraction = self._parse(raw_json)
        return self._validator.validate(extraction, report_text)

    def _generate_with_retries(self, report_text: str) -> str:
        last_error: AIGatewayError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.generate_json(
                    system_instruction=SYSTEM_PROMPT,
                    prompt=_build_prompt(report_text),
                )
            except AIGatewayError as exc:
                last_error = exc
                if attempt < self._max_retries:
                    time.sleep(self._retry_backoff_seconds * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _parse(self, raw_json: str) -> AIExtraction:
        if not raw_json.strip():
            raise AIResponseError("AI returned an empty response.")

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise AIResponseError(
                "AI returned malformed JSON that could not be decoded."
            ) from exc

        try:
            return AIExtraction.model_validate(data)
        except ValidationError as exc:
            raise AIResponseError(
                "AI output did not match the expected structure."
            ) from exc