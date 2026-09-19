import json

from pydantic import ValidationError

from app.ai.client import AIClient
from app.ai.errors import AIResponseError
from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schemas import AIExtraction


def _build_prompt(report_text: str) -> str:
    return f"Report text:\n{report_text}"


class AIService:
    """Orchestrates AI analysis of a report's original text.

    Depends on the AIClient interface only, so the real Gemini client can be
    replaced with a fake in tests and later swapped without changing callers.
    """

    def __init__(self, client: AIClient) -> None:
        self._client = client

    def analyze(self, report_text: str) -> AIExtraction:
        """Extract structured humanitarian information from report text."""
        raw_json = self._client.generate_json(
            system_instruction=SYSTEM_PROMPT,
            prompt=_build_prompt(report_text),
        )
        return self._validate(raw_json)

    def _validate(self, raw_json: str) -> AIExtraction:
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