from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_roles
from app.audit.schemas import AuditAction, AuditRecord
from app.core.container import get_audit_repository
from app.models.user import REVIEWER_ROLES, User
from app.repositories.audit_repository import AuditRepository

router = APIRouter(prefix="/api/audit", tags=["audit"])

_audit_reader = require_roles(*sorted(REVIEWER_ROLES))


@router.get("", response_model=list[AuditRecord])
def list_audit_records(
    repository: Annotated[AuditRepository, Depends(get_audit_repository)],
    current_user: Annotated[User, Depends(_audit_reader)],
    report_id: str | None = None,
    action: AuditAction | None = None,
) -> list[AuditRecord]:
    """Query the append-only audit trail (REVIEWER or ADMIN only).

    Optional filters: report ID and audit action. Records are returned newest
    first. The audit log is immutable: no endpoint edits or deletes records,
    and no update/delete method exists on the repository interface.
    """
    records = repository.get_all()
    if report_id is not None:
        records = [r for r in records if r.report_id == report_id]
    if action is not None:
        records = [r for r in records if r.action == action]
    return sorted(records, key=lambda r: r.timestamp, reverse=True)