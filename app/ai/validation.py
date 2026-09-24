from app.ai.classification import NeedClassifier
from app.ai.schemas import AIExtraction, NeedCategory


class AIValidator:
    """Backend-side validation and normalization of AI output.

    Gemini extracts information; this layer controls the final result:
    - enforces the controlled need category set
    - merges AI-reported needs with deterministic backend classification
    - guarantees a category (OTHER) when no clear need is identified
    - preserves uncertainty instead of guessing
    """

    def __init__(self, classifier: NeedClassifier | None = None) -> None:
        self._classifier = classifier or NeedClassifier()

    def validate(self, extraction: AIExtraction, original_text: str) -> AIExtraction:
        needs = self._merged_needs(extraction.needs, original_text)
        return extraction.model_copy(update={"needs": needs})

    def _merged_needs(
        self, extracted: list[NeedCategory], original_text: str
    ) -> list[NeedCategory]:
        classified = self._classifier.classify(original_text)
        # Keep AI order first, then backend-confirmed categories not already present.
        merged = list(dict.fromkeys([*extracted, *classified]))
        if not merged:
            return [NeedCategory.OTHER]
        return merged