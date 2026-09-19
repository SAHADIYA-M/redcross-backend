from typing import Protocol

from google import genai
from google.genai import types

from app.ai.errors import AIConfigurationError, AIGatewayError, AIResponseError


class AIClient(Protocol):
    """Contract for an AI client that returns structured JSON text."""

    def generate_json(self, *, system_instruction: str, prompt: str) -> str:
        """Send the prompt and return the model's plain JSON output."""
        ...


class GeminiClient:
    """Gemini-backed AI client using the google-genai SDK."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client: genai.Client | None = None

    def _require_client(self) -> genai.Client:
        if not self._api_key:
            raise AIConfigurationError(
                "Gemini is not configured: GEMINI_API_KEY is missing."
            )
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_json(self, *, system_instruction: str, prompt: str) -> str:
        client = self._require_client()

        try:
            response = client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
        except Exception as exc:
            raise AIGatewayError(f"Gemini request failed: {exc}") from exc

        if response is None or not response.text:
            raise AIResponseError("Gemini returned an empty response.")

        return response.text.strip()