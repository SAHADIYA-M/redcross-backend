"""Append-only audit log domain model.

Audit records are immutable. The AuditRepository deliberately exposes no
update or delete methods, and no API route lets a client modify an existing
record. A later PostgreSQL implementation must preserve this property.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AuditAction(str, Enum):
    """Controlled audit event types.

    Phase 9 audit entries mirror the verification actions. The enum is kept
    separate from VerificationAction so later phases can add audit events
    (e.g. report creation, status changes) without changing verification.
    """

    APPROVE = "APPROVE"
    EDIT = "EDIT"
    REJECT = "REJECT"
    MARK_UNCERTAIN = "MARK_UNCERTAIN"
    REQUEST_ASSESSMENT = "REQUEST_ASSESSMENT"


class AuditRecord(BaseModel):
    """Immutable record of a change to a report or its interpretation.

    old_value/new_value capture only the structured values that changed, so
    the original AI interpretation and the human correction both remain
    traceable without duplicating the full original report here. Sensitive
    information is never stored in the audit log.
    """

    audit_id: str
    report_id: str
    action: AuditAction
    actor_id: str | None = None
    timestamp: datetime
    reason: str | None = None
    old_value: dict[str, object] = Field(default_factory=dict)
    new_value: dict[str, object] = Field(default_factory=dict)