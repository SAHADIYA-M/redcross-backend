from pydantic import BaseModel, Field

from app.location.schemas import LocationResult


class GeocodeRequest(BaseModel):
    """Request schema for geocoding a raw location string."""

    raw_location: str = Field(min_length=1, description="Raw location text from the report.")


class GeocodeResponse(LocationResult):
    """Response schema for a location geocoding request.

    Reuses the validated LocationResult so coordinates/status are guaranteed
    to be consistent with the location domain rules.
    """