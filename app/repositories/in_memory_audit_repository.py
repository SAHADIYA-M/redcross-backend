from app.audit.schemas import AuditRecord
from app.repositories.audit_repository import AuditRepository


class InMemoryAuditRepository(AuditRepository):
    """Temporary append-only audit store backed by an in-memory dictionary.

    Records are only ever added, never updated or deleted, matching the
    immutability requirement. Replaced by a PostgreSQL implementation later.
    """

    def __init__(self) -> None:
        self._records: dict[str, AuditRecord] = {}

    def create(self, record: AuditRecord) -> AuditRecord:
        self._records[record.audit_id] = record
        return record

    def get_all(self) -> list[AuditRecord]:
        return list(self._records.values())