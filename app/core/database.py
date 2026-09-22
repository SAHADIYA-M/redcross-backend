"""Centralized PostgreSQL / Supabase database configuration.

Single place that owns:

- the application-level SQLAlchemy ``engine`` (created once, reused for the
  whole process — never one engine per request);
- the ``sessionmaker`` used by the PostgreSQL repositories;
- a FastAPI ``get_db`` dependency for routes/services that want a
  request-scoped session;
- a bounded health check that reuses the application engine and never
  exposes credentials;
- small domain exceptions for clean, non-leaky error handling.

The connection string always comes from ``DATABASE_URL`` in the environment;
credentials are never hardcoded here or anywhere else in source.
"""

import logging
import re
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger("app.database")


class DatabaseUnavailableError(Exception):
    """Raised when the database cannot be reached (down/timeout/reset)."""


class DatabaseIntegrityError(Exception):
    """Raised when a write violates a database constraint.

    Raised instead of leaking raw PostgreSQL constraint messages to clients.
    Callers may map it onto a 409 conflict or 422 as appropriate.
    """


def make_sqlalchemy_url(raw_url: str) -> str:
    """Normalize a ``DATABASE_URL`` into a SQLAlchemy-compatible URL.

    Supabase-style URLs are typically ``postgresql://user:pass@host:port/db``
    (or ``postgres://...``). SQLAlchemy needs a driver: ``psycopg`` (v3) is
    the project's PostgreSQL driver, so ``postgresql://`` URLs are mapped to
    ``postgresql+psycopg://`` centrally rather than being rewritten by each
    caller. Already-correct URLs pass through unchanged.
    """
    url = raw_url.strip()
    if not url:
        raise ValueError("DATABASE_URL is empty")
    if url.startswith("postgresql+psycopg://") or url.startswith(
        "postgresql+psycopg2://"
    ):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("sqlite://"):
        return url
    return url


def redact_url(url: str) -> str:
    """Return a log-safe copy of a database URL without any credentials."""
    try:
        return re.sub(r"(://[^:/@]+):([^@/]+)@", r"\1:***@", url)
    except Exception:  # pragma: no cover - defensive
        return "<unparseable-database-url>"


def _pool_options() -> dict:
    """Centralized engine kwargs for the Supabase pooler connection.

    ``pool_pre_ping`` keeps stale pooled connections from surfacing as
    request errors. Sizes stay modest because the app is a single-process API
    with a small request volume. All of this lives here so no other module
    makes ad-hoc pool decisions.
    """
    return {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 5,
    }


def _connect_timeout_kwargs(url: str, seconds: int) -> dict:
    """Connection-level options for PostgreSQL (bounded fail, pooler-safe).

    SQLite (offline tests) has no TCP connect step, so only PostgreSQL URLs
    get driver-level options:

    - ``connect_timeout`` keeps startup and request paths from blocking
      indefinitely when a configured database is unreachable;
    - ``prepare_threshold=None`` disables psycopg's server-side auto-prepared
      statements. The project's other psycopg code paths already pass
      ``prepare_threshold=None``: against a session-mode pooler (Supabase
      PgBouncer) a reused backend session keeps its prepared statement names
      (``_pg3_0``, ...), so a fresh connection's counter restart collides with
      ``DuplicatePreparedStatement`` and surfaces as an intermittent
      "Database unavailable". Disabling auto-prepare removes that class
      entirely at no cost for this workload.
    """
    if url.startswith("postgres") or url.startswith("postgresql"):
        return {
            "connect_args": {
                "connect_timeout": seconds,
                "prepare_threshold": None,
            }
        }
    return {}


_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_engine() -> Engine:
    """Return the process-wide application engine (created lazily).

    Creation is lazy so importing the app without a configured database never
    tries to connect. The engine itself does not connect until the first
    statement runs.
    """
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise DatabaseUnavailableError(
                "DATABASE_URL is not configured"
            )
        url = make_sqlalchemy_url(settings.database_url)
        logger.info(
            "Initializing database engine (url=%s)",
            redact_url(url),
        )
        try:
            kwargs = dict(_pool_options())
            kwargs.update(_connect_timeout_kwargs(url, seconds=5))
            _engine = create_engine(url, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            raise DatabaseUnavailableError(
                "Database engine could not be created"
            ) from exc
    return _engine


def reset_engine() -> None:
    """Dispose the cached engine/factory (tests only)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> sessionmaker:
    """Return the process-wide ``sessionmaker`` bound to the shared engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


def create_session() -> Session:
    """Open a new session from the shared factory."""
    return get_session_factory()()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session, always closing it."""
    session = create_session()
    try:
        yield session
    finally:
        session.close()


def translate_sqlalchemy_error(exc: SQLAlchemyError) -> Exception:
    """Map a SQLAlchemy error onto a safe domain exception.

    - a PostgreSQL unique-violation (pgcode 23505) becomes
      :class:`DatabaseIntegrityError` so callers can surface a clean 409;
    - a SQLite "UNIQUE constraint failed" (offline test suite) is translated
      the same way so the duplicate-identity path is exercised without a live
      database;
    - everything else becomes :class:`DatabaseUnavailableError` (temporarily
      unreachable/operation failed) — raw constraint messages, connection
      strings or stack details are never propagated to API clients.
    """
    original = getattr(exc, "orig", None)
    pgcode = (
        getattr(original, "pgcode", None)
        if original is not None
        else None
    )
    if pgcode == "23505":
        return DatabaseIntegrityError(
            "A record with the same identity already exists"
        )
    if original is not None and "UNIQUE constraint failed" in str(original):
        return DatabaseIntegrityError(
            "A record with the same identity already exists"
        )
    return DatabaseUnavailableError("Database operation failed")


def run_with_session(fn):
    """Execute ``fn(session)`` inside a short-lived session with rollback-on-error.

    Repository methods default to this pattern so transaction hygiene is
    centralized: every write is committed, and any failure rolls back instead
    of leaving the session in a failed state.
    """
    session = create_session()
    try:
        result = fn(session)
        session.commit()
        return result
    except DatabaseUnavailableError:
        session.rollback()
        raise
    except DatabaseIntegrityError:
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise translate_sqlalchemy_error(exc) from exc
    finally:
        session.close()


def check_database_health(timeout_seconds: float = 2.0) -> bool:
    """Return True when a trivial ``SELECT 1`` succeeds on the shared engine.

    Never raises: a false result simply means the database is currently
    unreachable. The check reuses the process-wide application engine
    (``get_engine()``) instead of opening a SECOND engine with a second pool:
    against the Supabase pooler that extra pool competes with the application
    pool for the pooler's client-connection budget and can be refused with
    ``ConnectionTimeout`` even while the application's own connections are
    perfectly healthy — which made the old check report "degraded" for a
    working database.

    Boundedness is inherited from the shared engine itself: PostgreSQL
    connections honor ``connect_timeout`` (5s) and pool checkouts honor
    ``pool_timeout`` (5s), so /health fails fast instead of hanging when the
    database is genuinely down. ``timeout_seconds`` is kept for callers that
    pass it, but the effective worst-case latency is set by the application
    engine's timeouts, not by a dedicated probe. No connection details are
    exposed.
    """
    if not settings.database_url:
        return False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health checks must never raise
        return False