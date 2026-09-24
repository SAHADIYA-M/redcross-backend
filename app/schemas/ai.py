from pydantic import BaseModel, Field

from app.ai.schemas import AIExtraction
from app.schemas.report import MAX_REPORT_TEXT_LENGTH


class AnalyzeRequest(BaseModel):
    """Request schema for AI analysis of a report."""

    original_text: str = Field(min_length=1, max_length=MAX_REPORT_TEXT_LENGTH)


class AnalyzeResponse(BaseModel):
    """Response schema for AI analysis.

    The original report text is echoed back unchanged, keeping it separate from
    the AI-generated structured result.
    """

    original_text: str
    extraction: AIExtraction