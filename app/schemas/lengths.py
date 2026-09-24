"""Shared text/list length limits for API input schemas.

A single source of truth so every write path is bounded identically: a
request payload cannot exhaust memory or storage, while the limits stay
generous for real humanitarian field data. Oversized payloads are rejected
by schema validation (422), never silently truncated.
"""

MAX_REPORT_TEXT_LENGTH = 50_000
MAX_REPORTER_LENGTH = 200
MAX_LOCATION_LENGTH = 500
MAX_INCIDENT_LENGTH = 500
MAX_SOURCE_LENGTH = 200
MAX_TIME_SENSITIVITY_LENGTH = 1_000
MAX_LIST_ITEMS = 50
MAX_EVIDENCE_ITEM_LENGTH = 2_000
MAX_VULNERABILITY_ITEM_LENGTH = 200

MAX_ACTIVITY_LENGTH = 5_000
MAX_NOTES_LENGTH = 50_000
MAX_REASON_LENGTH = 2_000
MAX_FULL_NAME_LENGTH = 128
MAX_PASSWORD_LENGTH = 128

# Free-text search/filter parameters. Report bodies may be up to 50k, but a
# substring query that large is never a useful operator need - these caps keep
# the pathological "megabyte query string" case out of every substring scan.
MAX_QUERY_LENGTH = 5_000
MAX_REPORT_ID_LENGTH = 64

# List endpoints return a bounded page by default so a single request cannot
# materialise the whole dataset in memory. Clients page through with explicit
# limit/offset; the default is generous for dashboards, the maximum keeps the
# response bounded (mirroring the search endpoint's MAX_PAGE_SIZE=100 scale).
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 1_000