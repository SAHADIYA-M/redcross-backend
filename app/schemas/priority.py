from app.priority.schemas import PriorityResult


class PriorityResponse(PriorityResult):
    """Response for the backend-computed priority of a report.

    Extends the priority domain result unchanged; the router only selects
    this schema so the API contract stays explicit.
    """