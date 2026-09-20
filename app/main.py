from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai import router as ai_router
from app.api.audit import router as audit_router
from app.api.conflicts import router as conflicts_router
from app.api.duplicates import router as duplicates_router
from app.api.errors import register_exception_handlers
from app.api.locations import router as locations_router
from app.api.priority import router as priority_router
from app.api.reports import router as reports_router
from app.api.search import router as search_router
from app.api.verification import router as verification_router
from app.api.verification import verification_list_router
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
app.include_router(conflicts_router)
app.include_router(priority_router)
app.include_router(verification_router)
app.include_router(verification_list_router)
app.include_router(audit_router)
app.include_router(search_router)

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