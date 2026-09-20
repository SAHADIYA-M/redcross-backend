from abc import ABC, abstractmethod

from app.audit.schemas import AuditRecord


class AuditRepository(ABC):
    """Contract for the append-only audit store.

    Deliberately exposes no update or delete operations: audit records are
    immutable by design. A PostgreSQL implementation must preserve this
    property (e.g. via append-only tables and restricted privileges).
    """

    @abstractmethod
    def create(self, record: AuditRecord) -> AuditRecord:
        """Append a new audit record and return it."""

    @abstractmethod
    def get_all(self) -> list[AuditRecord]:
        """Return all stored audit records."""