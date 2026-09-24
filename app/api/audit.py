from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.audit.schemas import AuditAction, AuditRecord
from app.core.container import get_audit_repository
from app.repositories.audit_repository import AuditRepository
from app.schemas.lengths import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditRecord])
def list_audit_records(
    repository: Annotated[AuditRepository, Depends(get_audit_repository)],
    report_id: str | None = None,
    action: AuditAction | None = None,
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> list[AuditRecord]:
    """Query the append-only audit trail.

    Optional filters: report ID and audit action. Records are returned newest
    first, bounded by ``limit`` (1-1000, default 100) with ``offset`` paging.
    The audit log is immutable: no endpoint edits or deletes records, and no
    update/delete method exists on the repository interface.
    """
    records = repository.get_all()
    if report_id is not None:
        records = [r for r in records if r.report_id == report_id]
    if action is not None:
        records = [r for r in records if r.action == action]
    ordered = sorted(records, key=lambda r: r.timestamp, reverse=True)
    return ordered[offset : offset + limit]