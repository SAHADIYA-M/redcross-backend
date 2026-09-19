from typing import Protocol

from app.location.schemas import GeocodeMatch


class Geocoder(Protocol):
    """Contract for a geocoding provider.

    Implementations translate a raw location string into one or more candidate
    matches with optional confidence. Returning multiple matches means the
    location is ambiguous and must not be silently resolved.
    """

    source: str

    def geocode(self, raw_location: str) -> list[GeocodeMatch]:
        """Return candidate matches for a raw location string.

        An empty list means the provider found nothing.
        """
        ...