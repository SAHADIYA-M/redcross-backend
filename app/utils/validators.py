"""Shared cross-field validation rules for query schemas.

Consolidates the two rules that were duplicated across the search, map,
response, response-map and information-gap query schemas so every invalid
range produces the same message and therefore the same FastAPI 422 body
everywhere: an inverted date range and a partial or inverted bounding box.
"""

from datetime import datetime

from app.utils.datetime_utils import as_utc


def validate_time_range(
    start_time: datetime | None,
    end_time: datetime | None,
) -> None:
    """Raise ValueError when start_time is after end_time (API UTC convention)."""
    if (
        start_time is not None
        and end_time is not None
        and as_utc(start_time) > as_utc(end_time)
    ):
        raise ValueError("start_time must be <= end_time")


def validate_bbox(
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
    *,
    missing_message: str,
) -> None:
    """Raise ValueError for a partial or inverted bounding box.

    ``missing_message`` is the error for a partially-supplied box (the schema
    documents what the box means in its own context, e.g. "to define a
    bounding box" vs "to define the analysis area").
    """
    parts = (min_lat, max_lat, min_lon, max_lon)
    if any(part is not None for part in parts) and not all(
        part is not None for part in parts
    ):
        raise ValueError(missing_message)
    if min_lat is not None and max_lat is not None and min_lat > max_lat:
        raise ValueError("min_lat must be <= max_lat")
    if min_lon is not None and max_lon is not None and min_lon > max_lon:
        raise ValueError("min_lon must be <= max_lon")