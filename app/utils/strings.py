"""Shared string utility helpers."""


def contains_ci(haystack: str | None, needle: str) -> bool:
    """Case-insensitive substring check. Returns False when haystack is None."""
    if haystack is None:
        return False
    return needle.casefold() in haystack.casefold()
