from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.api.ai import router as ai_router
from app.api.analytics import router as analytics_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.fusion import router as fusion_router
from app.api.clusters import router as clusters_router
from app.api.conflicts import router as conflicts_router
from app.api.deps import get_auth_service
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
from app.core.config import settings
from app.core.database import DatabaseUnavailableError, check_database_health, get_engine
from app.models.db_models import create_all
from app.schemas.response import HealthResponse, MessageResponse
from app.services.auth_service import seed_development_admin

logger = logging.getLogger("app.main")

if settings.environment == "production":
    settings.effective_jwt_secret_key()

app = FastAPI(
    title=settings.app_name,
    description="Backend for the AI-Assisted Humanitarian Needs Assessment & "
    "Operational Intelligence system.",
    version=settings.app_version,
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

# Optional bootstrap: when explicitly enabled (DB_CREATE_TABLES_ON_STARTUP=true
# AND a DATABASE_URL is configured), create any missing Phase 15 tables via the
# additive ORM ``create_all``. Never enabled automatically, and never used as a
# substitute for the team's migration workflow. A database that is currently
# unreachable degrades gracefully instead of crashing startup.
if settings.db_create_tables_on_startup:
    if settings.database_url.strip() and settings.environment != "production":
        try:
            create_all(get_engine())
        except DatabaseUnavailableError:
            logger.warning("Skipping table bootstrap: database unavailable")

# Development-only seed: creates a single ADMIN account, but ONLY when
# SEED_DEV_ADMIN=true AND the environment is not production. Credentials come
# from the environment and are documented as development-only. When a database
# is configured but currently unreachable the seed is skipped gracefully so
# startup never crashes just because the database is down; real programming
# errors still propagate.
if settings.environment != "production" and settings.seed_dev_admin:
    try:
        seed_development_admin(get_auth_service())
    except DatabaseUnavailableError:
        logger.warning(
            "Skipping development admin seed: database unavailable"
        )


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