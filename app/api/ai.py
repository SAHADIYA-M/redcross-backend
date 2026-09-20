from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.client import GeminiClient
from app.ai.errors import AIConfigurationError, AIGatewayError, AIResponseError
from app.api.deps import get_current_active_user
from app.core.config import settings
from app.models.user import User
from app.schemas.ai import AnalyzeRequest, AnalyzeResponse
from app.services.ai_service import AIService

router = APIRouter(prefix="/api/ai", tags=["ai"])


def get_ai_service() -> AIService:
    """Build the AI service backed by the real Gemini client."""
    client = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return AIService(client)


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_report(
    data: AnalyzeRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[AIService, Depends(get_ai_service)],
) -> AnalyzeResponse:
    try:
        extraction = service.analyze(data.original_text)
    except AIConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI analysis is not configured (missing GEMINI_API_KEY).",
        ) from exc
    except AIGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI analysis service is currently unavailable.",
        ) from exc
    except AIResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI analysis returned an invalid response.",
        ) from exc

    return AnalyzeResponse(original_text=data.original_text, extraction=extraction)