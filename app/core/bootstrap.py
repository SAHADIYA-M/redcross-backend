"""Startup database bootstrap, executed once per process via the FastAPI lifespan.

Consolidates the schema-creation, schema-readiness and development-admin seed
steps that previously ran as unsafe import-time side effects in ``app.main``.
All three steps keep their pre-existing gating:

- ``DB_CREATE_TABLES_ON_STARTUP`` (default off, development-only) creates any
  missing application tables with ``create_all`` (additive — never drops,
  truncates or alters). A bootstrap that cannot reach the database now FAILS
  startup clearly instead of logging a warning and continuing with a missing
  schema.
- schema readiness is enforced by default outside development
  (``DB_ENFORCE_SCHEMA_READY=false`` turns it off; dev defaults to off so the
  hermetic test mode never touches a database). A production app therefore
  never silently operates against an incomplete Phase 15 schema.
- ``SEED_DEV_ADMIN`` seeding stays development-only, idempotent and executed
  exactly once per startup; an unreachable store degrades to a clear warning,
  exactly as before.

This module never prints or logs connection strings, credentials or API keys,
and never performs destructive operations.
"""

import logging

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import DatabaseUnavailableError, get_engine
from app.models.db_models import REQUIRED_TABLES, create_all

logger = logging.getLogger("app.bootstrap")


class StartupDatabaseError(RuntimeError):
    """Raised when the application cannot safely start with its database.

    The message is deliberately credential-free and single-line so operators
    see a clear, predictable failure without any sensitive detail.
    """


def _wants_table_bootstrap() -> bool:
    return (
        settings.db_create_tables_on_startup
        and settings.environment != "production"
    )


def _wants_seed() -> bool:
    return settings.seed_dev_admin and settings.environment != "production"


def missing_schema_tables(engine) -> list[str]:
    """Return the names of required application tables missing from the DB.

    Read-only inspection: never creates, alters or drops anything. A database
    that cannot be reached raises :class:`DatabaseUnavailableError`.
    """
    try:
        existing = set(inspect(engine).get_table_names())
    except SQLAlchemyError as exc:
        raise DatabaseUnavailableError("Schema inspection failed") from exc
    return [name for name in REQUIRED_TABLES if name not in existing]


def run_startup_bootstrap() -> None:
    """Run the one-per-startup database bootstrap and readiness checks.

    Safe no-op when no startup database work is enabled, so database-less
    installs and the hermetic test suite are never affected.
    """
    create_tables = _wants_table_bootstrap()
    enforce_ready = settings.enforce_schema_ready
    wants_seed = _wants_seed()

    if not create_tables and not enforce_ready and not wants_seed:
        return

    if create_tables or enforce_ready:
        _ensure_database_schema(create_tables=create_tables, enforce_ready=enforce_ready)
    _seed_development_admin_once()


def _ensure_database_schema(*, create_tables: bool, enforce_ready: bool) -> None:
    if not settings.database_url.strip():
        raise StartupDatabaseError(
            "Startup database bootstrap is enabled but DATABASE_URL is not "
            "configured. Refusing to start without the required database."
        )
    try:
        engine = get_engine()
        if create_tables:
            create_all(engine)
        if enforce_ready:
            missing = missing_schema_tables(engine)
            if missing:
                raise StartupDatabaseError(
                    "Required application tables are missing from the "
                    f"database: {', '.join(missing)}. Apply the database "
                    "migrations or enable DB_CREATE_TABLES_ON_STARTUP."
                )
    except StartupDatabaseError:
        raise
    except (DatabaseUnavailableError, SQLAlchemyError) as exc:
        raise StartupDatabaseError(
            "Database schema bootstrap failed; refusing to start without the "
            "required schema. Check that DATABASE_URL is reachable."
        ) from exc


def _seed_development_admin_once() -> None:
    """Seed the development admin exactly once, preserving existing behavior.

    Idempotent: an admin that already exists is never re-created. The unique
    index on ``lower(username)`` (team migration 001) additionally guards
    concurrent multi-worker startups. An unreachable store is skipped with a
    clear warning, exactly as before.
    """
    if not _wants_seed():
        return
    from app.core.container import get_auth_service
    from app.services.auth_service import seed_development_admin

    try:
        seed_development_admin(get_auth_service())
    except DatabaseUnavailableError as exc:
        logger.warning(
            "Development admin seed skipped: database unavailable: %s", exc
        )