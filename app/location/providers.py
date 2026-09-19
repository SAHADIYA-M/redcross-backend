from app.location.errors import GeocoderConfigurationError
from app.location.schemas import GeocodeMatch


class StubGeocoder:
    """Development-friendly geocoder backed by a small curated gazetteer.

    It requires no credentials and never makes network calls, which keeps the
    whole pipeline testable offline. It intentionally returns multiple matches
    for genuinely ambiguous names (e.g. "market") so the ambiguity path in the
    location service can be exercised without a live provider.

    Replace this provider in a later phase by implementing the Geocoder
    protocol (see app.location.geocoder) against a real service and pointing
    GEOCODER_PROVIDER at it.
    """

    source: str = "stub"

    # (match keywords, resolved name, latitude, longitude, confidence)
    # Keywords that appear on more than one entry (e.g. "market", "hospital")
    # make those names genuinely ambiguous so the location service can mark
    # them UNCERTAIN instead of guessing.
    _GAZETTEER: list[tuple[str, str, float, float, float]] = [
        ("kozhikode beach", "Kozhikode Beach, Kozhikode, Kerala, India", 11.2588, 75.7804, 0.98),
        ("old bus stand", "Old Bus Stand, Kozhikode, Kerala, India", 11.2602, 75.7620, 0.85),
        ("railway station", "Kozhikode Railway Station, Kozhikode, Kerala, India", 11.2531, 75.7808, 0.9),
        ("mananchira", "Mananchira Square, Kozhikode, Kerala, India", 11.2529, 75.7807, 0.75),
        ("market", "Central Market, Kozhikode, Kerala, India", 11.2582, 75.7788, 0.5),
        ("market", "Mananchira Market, Kozhikode, Kerala, India", 11.2529, 75.7807, 0.5),
        ("medical college", "Government Medical College, Kozhikode, Kerala, India", 11.2642, 75.7677, 0.9),
        ("hospital", "Government Medical College Hospital, Kozhikode, Kerala, India", 11.2642, 75.7677, 0.55),
        ("hospital", "Beach Hospital, Kozhikode, Kerala, India", 11.2601, 75.7749, 0.5),
    ]

    def geocode(self, raw_location: str) -> list[GeocodeMatch]:
        lowered = raw_location.lower()
        matches: list[GeocodeMatch] = []
        for keywords, resolved, lat, lon, confidence in self._GAZETTEER:
            if keywords in lowered:
                matches.append(
                    GeocodeMatch(
                        resolved_location=resolved,
                        latitude=lat,
                        longitude=lon,
                        confidence=confidence,
                    )
                )
        return matches


def build_geocoder(provider: str) -> object:
    """Factory for the configured geocoding provider.

    Only the stub is available in this phase because a real provider needs
    credentials and network access, which are out of scope until a provider is
    selected. GEOCODER_PROVIDER accepts "stub" today; unknown values raise a
    configuration error instead of pretending to work.
    """
    if provider == "stub":
        return StubGeocoder()
    raise GeocoderConfigurationError(
        f"Unknown geocoding provider: '{provider}'"
    )