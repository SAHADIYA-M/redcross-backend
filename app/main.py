from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from contextlib import asynccontextmanager

from app.api.ai import router as ai_router
from app.api.analytics import router as analytics_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.fusion import router as fusion_router
from app.api.clusters import router as clusters_router
from app.api.conflicts import router as conflicts_router
from app.api.duplicates import router as duplicates_router
from app.api.errors import register_exception_handlers
from app.api.locations import router as locations_router
from app.api.lookups import needs_router, priorities_router
from app.api.map import router as map_router
from app.api.map_responses import router as map_responses_router
from app.api.priority import router as priority_router
from app.api.reports import router as reports_router
from app.api.responses import router as responses_router
from app.api.search import router as search_router
from app.api.users import router as users_router
from app.api.verification import router as verification_router
from app.api.verification import verification_list_router
import app.core.bootstrap as bootstrap_module
from app.core.config import settings
from app.core.database import check_database_health
from app.schemas.response import HealthResponse, MessageResponse

logger = logging.getLogger("app.main")

if settings.environment != "development":
    # Any non-development environment must fail closed when no real JWT
    # secret is configured (production, staging, ...). Development keeps the
    # development-only fallback so local runs need no secret.
    settings.effective_jwt_secret_key()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database bootstrap (schema creation, schema readiness, development-admin
    # seed) runs here — once per process startup — instead of as an unsafe
    # import-time side effect. It is a safe no-op unless the operator enabled
    # the corresponding startup work.
    bootstrap_module.run_startup_bootstrap()
    yield


app = FastAPI(
    title=settings.app_name,
    description="Backend for the AI-Assisted Humanitarian Needs Assessment & "
    "Operational Intelligence system.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(reports_router)
app.include_router(clusters_router)
app.include_router(needs_router)
app.include_router(priorities_router)
app.include_router(ai_router)
app.include_router(locations_router)
app.include_router(duplicates_router)
app.include_router(conflicts_router)
app.include_router(priority_router)
app.include_router(verification_router)
app.include_router(verification_list_router)
app.include_router(audit_router)
app.include_router(search_router)
app.include_router(map_router)
app.include_router(responses_router)
app.include_router(map_responses_router)
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(fusion_router)

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
    if settings.database_url.strip():
        if check_database_health():
            return HealthResponse(status="healthy", database="healthy")
        return HealthResponse(status="degraded", database="unavailable")
    return HealthResponse(status="healthy")