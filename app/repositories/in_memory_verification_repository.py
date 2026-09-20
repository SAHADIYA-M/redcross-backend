from app.repositories.verification_repository import VerificationRepository
from app.verification.schemas import VerificationRecord


class InMemoryVerificationRepository(VerificationRepository):
    """Temporary verification store backed by an in-memory dictionary.

    Replaced by a PostgreSQL-backed repository in a later phase.
    """

    def __init__(self) -> None:
        self._records: dict[str, VerificationRecord] = {}

    def create(self, record: VerificationRecord) -> VerificationRecord:
        self._records[record.verification_id] = record
        return record

    def get_all(self) -> list[VerificationRecord]:
        return list(self._records.values())