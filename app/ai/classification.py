import re

from app.ai.schemas import NeedCategory

# Keyword sets are matched against the lowercase report text. Categories are
# iterated in declaration order so the classifier output is deterministic.
_KEYWORDS: dict[NeedCategory, tuple[str, ...]] = {
    NeedCategory.WATER: ("water", "drink", "thirst", "drought", "well", "pipe", "borehole"),
    NeedCategory.FOOD: ("food", "hungry", "hunger", "meal", "starve", "starvation", "famine", "grain", "rice", "nutrition"),
    NeedCategory.SHELTER: ("shelter", "home", "house", "roof", "tent", "homeless", "housing", "evicted"),
    NeedCategory.HEALTHCARE: ("clinic", "hospital", "health", "medicine", "medical", "doctor", "nurse", "injured", "injury", "treatment", "sick", "ill", "wound", "vaccine", "patient"),
    NeedCategory.SANITATION: ("sanitation", "toilet", "latrine", "sewage", "waste", "hygiene", "sewer"),
    NeedCategory.PROTECTION: ("protection", "violence", "abuse", "safety", "traffick", "unaccompanied", "exploitation", "child soldier"),
    NeedCategory.ESSENTIAL_ITEMS: ("blanket", "clothes", "clothing", "soap", "supplies", "kit", "mattress", "cooking", "medicine", "mask"),
    NeedCategory.TRANSPORTATION: ("transport", "road", "bridge", "vehicle", "bus", "blocked", "isolated", "access", "fuel"),
    NeedCategory.COMMUNICATION: ("communication", "phone", "network", "radio", "signal", "internet", "mobile service"),
    NeedCategory.INFRASTRUCTURE_SERVICE: ("electric", "power", "electricity", "grid", "school", "market", "infrastructure", "service", "facility"),
    NeedCategory.OTHER: (),
}


def _matches_text(text: str, keyword: str) -> bool:
    """Match on word boundaries to avoid substring false positives.

    e.g. "ill" must not match "village"; "water" must match "drinking water".
    """
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}s?\b", text) is not None


class NeedClassifier:
    """Deterministic, keyword-based humanitarian need classification.

    The AI extracts needs; this backend layer independently confirms and
    enforces membership in the controlled category set. It never guesses: a
    category is only returned when the report text mentions related keywords.
    """

    def classify(self, text: str) -> list[NeedCategory]:
        lowered = text.lower()
        return [
            category
            for category, keywords in _KEYWORDS.items()
            if keywords and any(_matches_text(lowered, keyword) for keyword in keywords)
        ]