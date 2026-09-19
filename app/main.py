from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai import router as ai_router
from app.api.duplicates import router as duplicates_router
from app.api.errors import register_exception_handlers
from app.api.locations import router as locations_router
from app.api.reports import router as reports_router
from app.core.config import settings
from app.schemas.response import HealthResponse, MessageResponse

app = FastAPI(
    title=settings.app_name,
    description="Backend for the AI-Assisted Humanitarian Needs Assessment & "
    "Operational Intelligence system.",
    version=settings.app_version,
)

app.include_router(reports_router)
app.include_router(ai_router)
app.include_router(locations_router)
app.include_router(duplicates_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.get("/", response_model=MessageResponse)
def root() -> MessageResponse:
    return MessageResponse(message="Backend is running")


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="healthy")