class LocationError(Exception):
    """Base class for location/geocoding errors."""


class GeocoderConfigurationError(LocationError):
    """Raised when no usable geocoding provider is configured."""


class GeocoderUnavailableError(LocationError):
    """Raised when a geocoding provider cannot be reached (network, API)."""


class GeocoderTimeoutError(LocationError):
    """Raised when a geocoding provider times out."""


class GeocoderInvalidResponseError(LocationError):
    """Raised when a geocoder returns malformed or out-of-range data."""