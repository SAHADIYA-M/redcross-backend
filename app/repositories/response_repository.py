from abc import ABC, abstractmethod

from app.response_activity.schemas import ResponseActivity


class ResponseRepository(ABC):
    """Contract for storing and retrieving response activities.

    The API and service layers depend on this interface only. Concrete
    implementations (in-memory today, PostgreSQL later) can be swapped without
    changing the rest of the application. Identity is preserved across status
    updates: update() replaces the stored activity in place, it never creates a
    duplicate record.
    """

    @abstractmethod
    def create(self, response: ResponseActivity) -> ResponseActivity:
        """Persist a new response activity and return it."""

    @abstractmethod
    def get_by_id(self, response_id: str) -> ResponseActivity | None:
        """Return the activity with the given id, or None if not found."""

    @abstractmethod
    def get_all(self) -> list[ResponseActivity]:
        """Return all stored response activities."""

    @abstractmethod
    def update(
        self, response_id: str, response: ResponseActivity
    ) -> ResponseActivity | None:
        """Replace the stored activity with the given one; None if not found."""