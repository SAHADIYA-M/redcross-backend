from enum import Enum

from pydantic import BaseModel, Field


class LocationStatus(str, Enum):
    """Confidence status of a geocoded location.

    CONFIRMED: a single location was resolved with acceptable certainty.
    UNCERTAIN: ambiguous, missing, or low-confidence location (never guessed).
    """

    CONFIRMED = "CONFIRMED"
    UNCERTAIN = "UNCERTAIN"


class GeocodeMatch(BaseModel):
    """A single candidate returned by a geocoding provider.

    The optional confidence reflects whatever quality indicator the provider
    gives. If the provider does not supply one, confidence stays None — it is
    never invented by the application.
    """

    resolved_location: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class LocationResult(BaseModel):
    """Validated result of a location geocoding request.

    The raw location is always preserved verbatim and is never replaced by the
    coordinates. Coordinates and confidence are only present when the result
    is CONFIRMED; uncertainty is represented by status, never by guessing.
    """

    raw_location: str | None = None
    resolved_location: str | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str
    status: LocationStatus