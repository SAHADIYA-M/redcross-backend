import json

from pydantic import ValidationError

from app.ai.client import AIClient
from app.ai.errors import AIResponseError
from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schemas import AIExtraction
from app.ai.validation import AIValidator


def _build_prompt(report_text: str) -> str:
    return f"Report text:\n{report_text}"


class AIService:
    """Orchestrates the AI analysis pipeline.

    Pipeline: send report text to the AI client -> parse and strictly validate
    the JSON with Pydantic -> backend validation and need classification.

    Depends on the AIClient interface only, so the real Gemini client can be
    replaced with a fake in tests and later swapped without changing callers.
    """

    def __init__(
        self,
        client: AIClient,
        validator: AIValidator | None = None,
    ) -> None:
        self._client = client
        self._validator = validator or AIValidator()

    def analyze(self, report_text: str) -> AIExtraction:
        """Return the backend-validated structured information for a report."""
        raw_json = self._client.generate_json(
            system_instruction=SYSTEM_PROMPT,
            prompt=_build_prompt(report_text),
        )
        extraction = self._parse(raw_json)
        return self._validator.validate(extraction, report_text)

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