from enum import Enum

from pydantic import BaseModel, Field, field_validator


class NeedCategory(str, Enum):
    """Allowed humanitarian need categories."""

    WATER = "WATER"
    FOOD = "FOOD"
    SHELTER = "SHELTER"
    HEALTHCARE = "HEALTHCARE"
    SANITATION = "SANITATION"
    PROTECTION = "PROTECTION"
    ESSENTIAL_ITEMS = "ESSENTIAL_ITEMS"
    TRANSPORTATION = "TRANSPORTATION"
    COMMUNICATION = "COMMUNICATION"
    INFRASTRUCTURE_SERVICE = "INFRASTRUCTURE_SERVICE"
    OTHER = "OTHER"


class SeverityLevel(str, Enum):
    """Disaster severity extracted from the report."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AIExtraction(BaseModel):
    """Structured data extracted from a report by the AI.

    Values are null/empty when the report does not provide the information.
    Validation is strict: malformed data is rejected, never silently accepted.
    The final priority is NOT decided here — it is computed in a later phase.
    """

    incident: str | None = None
    location: str | None = None
    needs: list[NeedCategory] = Field(default_factory=list)
    severity: SeverityLevel | None = None
    affected_population: int | None = None
    vulnerability: list[str] = Field(default_factory=list)
    time_sensitivity: str | None = None
    evidence: list[str] = Field(default_factory=list)

    @field_validator("incident", "location", "time_sensitivity", mode="after")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("affected_population", mode="before")
    @classmethod
    def _validate_population(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("affected_population must be an integer or null")
        if isinstance(value, int):
            if value < 0:
                raise ValueError("affected_population cannot be negative")
            return value
        if isinstance(value, float):
            if value.is_integer() and value >= 0:
                return int(value)
            raise ValueError("affected_population must be a whole number or null")
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
            raise ValueError("affected_population must be a number or null")
        raise ValueError("affected_population must be an integer or null")

    @field_validator("vulnerability", "evidence", mode="after")
    @classmethod
    def _clean_text_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in values:
            stripped = item.strip()
            if stripped and stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned

    @field_validator("needs", mode="after")
    @classmethod
    def _dedupe_needs(cls, needs: list[NeedCategory]) -> list[NeedCategory]:
        return list(dict.fromkeys(needs))