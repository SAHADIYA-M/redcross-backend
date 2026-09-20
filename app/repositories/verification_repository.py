from abc import ABC, abstractmethod

from app.verification.schemas import VerificationRecord


class VerificationRepository(ABC):
    """Contract for storing verification records.

    The verification service depends on this interface only. Concrete
    implementations (in-memory today, PostgreSQL later) can be swapped
    without changing the rest of the application.
    """

    @abstractmethod
    def create(self, record: VerificationRecord) -> VerificationRecord:
        """Append a new verification record and return it."""

    @abstractmethod
    def get_all(self) -> list[VerificationRecord]:
        """Return all stored verification records."""

    @abstractmethod
    def get_by_report(self, report_id: str) -> list[VerificationRecord]:
        """Return verification records for a single report, oldest first."""