from abc import ABC, abstractmethod

from app.models.report import Report


class ReportRepository(ABC):
    """Contract for storing and retrieving reports.

    The API and service layers depend on this interface only. Concrete
    implementations (in-memory today, PostgreSQL later) can be swapped
    without changing the rest of the application.
    """

    @abstractmethod
    def create(self, report: Report) -> Report:
        """Persist a new report and return it."""

    @abstractmethod
    def get_by_id(self, report_id: str) -> Report | None:
        """Return the report with the given id, or None if not found."""

    @abstractmethod
    def get_all(self) -> list[Report]:
        """Return all stored reports."""

    @abstractmethod
    def update(self, report_id: str, report: Report) -> Report | None:
        """Replace the stored report with the given one; None if not found."""