"""Domain models and controlled enums for the human verification workflow."""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.ai.schemas import NeedCategory, SeverityLevel
from app.conflicts.schemas import InfrastructureStatus
from app.schemas.lengths import (
    MAX_INCIDENT_LENGTH,
    MAX_LIST_ITEMS,
    MAX_LOCATION_LENGTH,
    MAX_TIME_SENSITIVITY_LENGTH,
    MAX_VULNERABILITY_ITEM_LENGTH,
)


class VerificationStatus(str, Enum):
    """Verification state of a report's structured interpretation.

    AI output is never verified by the AI. A report starts UNVERIFIED and can
    only move to another state through a human verification action.
    ASSESSMENT_REQUESTED marks a report flagged for further field/human
    assessment: it is a request, never a verification result.
    """

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"
    ASSESSMENT_REQUESTED = "ASSESSMENT_REQUESTED"


class VerificationAction(str, Enum):
    """Controlled human verification actions accepted by the API.

    Only these actions may be submitted; any other value is rejected by
    validation before it reaches the service layer.
    """

    APPROVE = "APPROVE"
    EDIT = "EDIT"
    REJECT = "REJECT"
    MARK_UNCERTAIN = "MARK_UNCERTAIN"
    REQUEST_ASSESSMENT = "REQUEST_ASSESSMENT"


class VerificationEdits(BaseModel):
    """Controlled corrections a reviewer may apply with the EDIT action.

    Only structured interpretation fields that already exist on a report are
    editable. Original evidence is never editable, so the original report can
    never be overwritten:

    - original_text, evidence, source, reporter, timestamp are NOT editable;
    - unknown fields are rejected (extra="forbid") instead of silently
      ignored, so an attempted correction of a non-existent field fails
      loudly.
    """

    model_config = ConfigDict(extra="forbid")

    needs: list[NeedCategory] | None = Field(
        default=None,
        max_length=MAX_LIST_ITEMS,
        description="Corrected need categories.",
    )
    severity: SeverityLevel | None = Field(
        default=None, description="Corrected severity claim."
    )
    affected_population: int | None = Field(
        default=None, ge=0, description="Corrected affected population count."
    )
    vulnerability: list[
        Annotated[str, StringConstraints(max_length=MAX_VULNERABILITY_ITEM_LENGTH)]
    ] | None = Field(
        default=None,
        max_length=MAX_LIST_ITEMS,
        description="Corrected vulnerable groups.",
    )
    time_sensitivity: str | None = Field(
        default=None,
        max_length=MAX_TIME_SENSITIVITY_LENGTH,
        description="Corrected time-sensitivity statement.",
    )
    location: str | None = Field(
        default=None, max_length=MAX_LOCATION_LENGTH, description="Corrected location."
    )
    incident: str | None = Field(
        default=None, max_length=MAX_INCIDENT_LENGTH, description="Corrected incident."
    )
    infrastructure_status: InfrastructureStatus | None = Field(
        default=None, description="Corrected infrastructure/service status."
    )
    available_needs: list[NeedCategory] | None = Field(
        default=None,
        max_length=MAX_LIST_ITEMS,
        description="Corrected available needs.",
    )


class VerificationRecord(BaseModel):
    """A single human verification action against a report.

    Records are append-only in the spirit of the workflow: new actions create
    new records, existing records are never rewritten. The `changes` field
    holds field-level old/new values for EDIT actions so the AI-generated
    value and the human correction both stay traceable.
    """

    verification_id: str
    report_id: str
    action: VerificationAction
    previous_status: VerificationStatus | None = None
    new_status: VerificationStatus | None = None
    reviewer_id: str | None = None
    reason: str | None = None
    timestamp: datetime
    changes: dict[str, dict[str, object]] = Field(
        default_factory=dict,
        description=(
            "Field-level corrections for EDIT: field name -> "
            "{'old': <AI value>, 'new': <human value>}."
        ),
    )