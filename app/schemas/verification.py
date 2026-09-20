"""Request/response schemas for the human verification API."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.priority import PriorityResponse
from app.schemas.report import ReportResponse
from app.verification.schemas import (
    VerificationAction,
    VerificationEdits,
    VerificationRecord,
)


class VerifyRequest(BaseModel):
    """Body of PATCH /api/reports/{report_id}/verify.

    Only the four PATCH actions are accepted here: APPROVE, EDIT, REJECT and
    MARK_UNCERTAIN. REQUEST_ASSESSMENT is submitted to the dedicated
    POST /api/reports/{report_id}/request-assessment endpoint instead. A
    reviewer can never submit a priority score; final scores are always
    computed by the backend.
    """

    model_config = ConfigDict(extra="forbid")

    action: VerificationAction = Field(
        description="Verification action to perform (APPROVE, EDIT, REJECT, MARK_UNCERTAIN)."
    )
    reason: str | None = Field(
        default=None,
        description="Reason or comment for the action (required for REJECT).",
    )
    reviewer_id: str | None = Field(
        default=None,
        description=(
            "Optional reviewer identifier. Authentication is not implemented "
            "yet, so this is a nullable field to be connected to auth later."
        ),
    )
    edits: VerificationEdits | None = Field(
        default=None,
        description="Controlled structured corrections; required for the EDIT action.",
    )

    @model_validator(mode="after")
    def _validate_action_requirements(self) -> "VerifyRequest":
        if self.action == VerificationAction.REQUEST_ASSESSMENT:
            raise ValueError(
                "REQUEST_ASSESSMENT must be sent to POST "
                "/api/reports/{id}/request-assessment"
            )
        if self.action == VerificationAction.EDIT:
            if self.edits is None or not self.edits.model_dump(exclude_unset=True):
                raise ValueError("EDIT requires at least one field in 'edits'")
        elif self.edits is not None:
            raise ValueError("'edits' is only allowed for the EDIT action")
        if self.action == VerificationAction.REJECT and not (self.reason or "").strip():
            raise ValueError("REJECT requires a non-empty 'reason'")
        return self


class RequestAssessmentRequest(BaseModel):
    """Body of POST /api/reports/{report_id}/request-assessment.

    Flagging a report for assessment is a request, not a verification result:
    the report is marked ASSESSMENT_REQUESTED and is never treated as
    verified by this action.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        min_length=1,
        description="Why the report needs further human assessment.",
    )
    reviewer_id: str | None = Field(
        default=None,
        description="Optional reviewer identifier (auth is a later phase).",
    )


class VerifyResponse(BaseModel):
    """Result of a verification action.

    Contains the updated report, the recorded verification, and (for EDIT) the
    backend-recalculated priority. priority is None when the edited report no
    longer carries usable priority input: the derived value is invalidated
    rather than forced by the reviewer.
    """

    report: ReportResponse
    verification: VerificationRecord
    priority: PriorityResponse | None = Field(
        default=None,
        description=(
            "Recalculated priority after an EDIT. None for other actions or "
            "when the edited report no longer carries usable priority input."
        ),
    )


class AssessmentRequestResponse(BaseModel):
    """Result of a request-assessment action."""

    report: ReportResponse
    verification: VerificationRecord