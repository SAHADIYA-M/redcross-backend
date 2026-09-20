"""Shared datetime utility helpers."""

from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    """Normalize a datetime for comparison without shifting its meaning.

    Aware values are converted to UTC preserving the instant; naive values are
    treated as UTC (the API's convention) rather than being guessed to be
    local time.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
