"""Batch 2 regression tests: safe database startup/bootstrap + schema readiness.

Covers the move of database bootstrap from unsafe import-time side effects into
the FastAPI lifespan, the create-all/readiness/seed behavior, clean failure when
the database is unavailable during bootstrap, and the guarantee that nothing
destructive ever happens to existing tables or data.

All tests run fully offline (SQLite stand-in for the shared engine, or no
engine at all).
"""

import pytest
from fastapi.testclient import TestClient

import app.core.database as db
import app.core.bootstrap as bootstrap_module
from app.core.bootstrap import StartupDatabaseError
from app.core.database import DatabaseUnavailableError
from app.main import app
from app.models.db_models import REQUIRED_TABLES
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


@pytest.fixture(autouse=True)
def _isolate_engine():
    db.reset_engine()
    yield
    db.reset_engine()


class _BrokenEngine:
    """Fake engine whose DDL step fails like an unreachable database."""

    def _run_ddl_visitor(self, visitorcls, element, **kwargs):
        raise DatabaseUnavailableError("database is down")


def _use_sqlite(monkeypatch) -> db.Engine:
    monkeypatch.setattr(bootstrap_module.settings, "database_url", "sqlite://")
    monkeypatch.setattr(db, "_pool_options", lambda: {})
    return db.get_engine()


# ---------------------------------------------------------------------------
# Disabled startup work must never touch a database
# ---------------------------------------------------------------------------


def test_bootstrap_noop_when_no_database_configured(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap_module.settings, "database_url", "")
    monkeypatch.setattr(
        bootstrap_module,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("engine must not be built")),
    )
    # In development the default preserves the old defaults: no table creation,
    # no readiness enforcement, no seed.
    bootstrap_module.run_startup_bootstrap()


def test_bootstrap_noop_when_all_startup_work_disabled(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap_module.settings, "database_url", "postgresql://db.example/db")
    monkeypatch.setattr(bootstrap_module.settings, "db_create_tables_on_startup", False)
    monkeypatch.setattr(bootstrap_module.settings, "enforce_schema_ready", False)
    monkeypatch.setattr(bootstrap_module.settings, "seed_dev_admin", False)
    monkeypatch.setattr(
        bootstrap_module,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("engine must not be built")),
    )
    bootstrap_module.run_startup_bootstrap()


# ---------------------------------------------------------------------------
# Table creation when enabled
# ---------------------------------------------------------------------------


def test_enabled_bootstrap_creates_schema(monkeypatch) -> None:
    engine = _use_sqlite(monkeypatch)
    monkeypatch.setattr(bootstrap_module.settings, "db_create_tables_on_startup", True)
    monkeypatch.setattr(bootstrap_module.settings, "enforce_schema_ready", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")

    bootstrap_module.run_startup_bootstrap()

    assert bootstrap_module.missing_schema_tables(engine) == []


def test_bootstrap_without_database_url_fails_clearly(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap_module.settings, "database_url", "")
    monkeypatch.setattr(bootstrap_module.settings, "db_create_tables_on_startup", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")
    with pytest.raises(StartupDatabaseError):
        bootstrap_module.run_startup_bootstrap()


# ---------------------------------------------------------------------------
# Database unavailable / SQLAlchemy errors -> clear, credential-free failure
# ---------------------------------------------------------------------------


def test_bootstrap_fails_clearly_when_database_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap_module.settings, "database_url", "postgresql://db.example/db")
    monkeypatch.setattr(bootstrap_module.settings, "db_create_tables_on_startup", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")
    monkeypatch.setattr(bootstrap_module, "get_engine", lambda: _BrokenEngine())

    with pytest.raises(StartupDatabaseError) as excinfo:
        bootstrap_module.run_startup_bootstrap()
    message = str(excinfo.value).lower()
    assert "schema" in message
    # No raw internals / credentials in the surfaced message.
    assert "postgresql" not in message
    assert "db.example" not in message
    assert "password" not in message


def test_bootstrap_fails_clearly_on_sqlalchemy_error(monkeypatch) -> None:
    class _PoisonEngine:
        def _run_ddl_visitor(self, visitorcls, element, **kwargs):
            raise SQLAlchemyError("simulated driver failure during schema DDL")

    monkeypatch.setattr(bootstrap_module.settings, "db_create_tables_on_startup", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")
    monkeypatch.setattr(bootstrap_module, "get_engine", lambda: _PoisonEngine())

    with pytest.raises(StartupDatabaseError):
        bootstrap_module.run_startup_bootstrap()


# ---------------------------------------------------------------------------
# Schema readiness enforcement (complete vs missing, non-destructive)
# ---------------------------------------------------------------------------


def test_readiness_passes_when_schema_complete(monkeypatch) -> None:
    engine = _use_sqlite(monkeypatch)
    from app.models.db_models import create_all

    create_all(engine)
    monkeypatch.setattr(bootstrap_module.settings, "enforce_schema_ready", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "production")
    bootstrap_module.run_startup_bootstrap()


def test_readiness_fails_clearly_when_schema_missing(monkeypatch) -> None:
    _use_sqlite(monkeypatch)
    monkeypatch.setattr(bootstrap_module.settings, "enforce_schema_ready", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "production")

    with pytest.raises(StartupDatabaseError) as excinfo:
        bootstrap_module.run_startup_bootstrap()
    message = excinfo.value.args[0]
    # Names a missing required table, not connection details.
    assert "reports" in message
    assert "missing" in message


def test_readiness_defaults_off_in_development(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap_module.settings, "enforce_schema_ready", False)
    _use_sqlite(monkeypatch)
    # No raise: dev does not enforce readiness by default.
    bootstrap_module.run_startup_bootstrap()


def test_bootstrap_is_non_destructive_to_existing_tables_and_data(
    monkeypatch,
) -> None:
    engine = _use_sqlite(monkeypatch)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE legacy_team_table (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO legacy_team_table (name) VALUES ('kept-data')"))
        conn.execute(text("CREATE TABLE reports (report_id TEXT PRIMARY KEY)"))
        conn.execute(text("INSERT INTO reports (report_id) VALUES ('existing-1')"))

    monkeypatch.setattr(bootstrap_module.settings, "db_create_tables_on_startup", True)
    monkeypatch.setattr(bootstrap_module.settings, "enforce_schema_ready", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")

    bootstrap_module.run_startup_bootstrap()

    with engine.connect() as conn:
        legacy = conn.execute(text("SELECT name FROM legacy_team_table")).fetchall()
        preserved = conn.execute(
            text("SELECT report_id FROM reports WHERE report_id = 'existing-1'")
        ).fetchall()
    assert [row[0] for row in legacy] == ["kept-data"]
    assert [row[0] for row in preserved] == ["existing-1"]
    assert bootstrap_module.missing_schema_tables(engine) == []


# ---------------------------------------------------------------------------
# Seed behavior: once per lifecycle, idempotent
# ---------------------------------------------------------------------------


def test_seed_runs_exactly_once_per_lifecycle(monkeypatch) -> None:
    calls = []

    def _recording_seed(service):
        calls.append(service)

    monkeypatch.setattr(bootstrap_module.settings, "seed_dev_admin", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")
    monkeypatch.setattr(
        "app.services.auth_service.seed_development_admin", _recording_seed
    )
    monkeypatch.setattr(
        "app.core.container.get_auth_service", lambda: object()
    )

    bootstrap_module.run_startup_bootstrap()
    assert len(calls) == 1


def test_seed_is_idempotent_when_admin_already_exists(monkeypatch) -> None:
    from app.repositories import InMemoryUserRepository
    from app.services.auth_service import AuthService, seed_development_admin
    from app.schemas.auth import UserCreate

    monkeypatch.setattr(bootstrap_module.settings, "seed_dev_admin", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")

    service = AuthService(InMemoryUserRepository())
    service.register(
        UserCreate(username="dev_admin", password="supersecret1"),
        role="ADMIN",
    )
    # Running the seed again must not create a duplicate admin.
    seed_development_admin(service)
    seed_development_admin(service)
    admins = [u for u in service.list_users() if u.role.value == "ADMIN"]
    assert len(admins) == 1


# ---------------------------------------------------------------------------
# Health endpoint + lifespan integration
# ---------------------------------------------------------------------------


def test_lifespan_runs_bootstrap_once_and_health_unaffected(monkeypatch) -> None:
    import app.main as main_module

    calls: list = []

    class _Module:
        @staticmethod
        def run_startup_bootstrap() -> None:
            calls.append(True)

    monkeypatch.setattr(main_module, "bootstrap_module", _Module())
    monkeypatch.setattr(bootstrap_module.settings, "database_url", "")

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "database": None}

    assert len(calls) == 1, "bootstrap must run exactly once per startup"


def test_startup_fails_clearly_when_enabled_bootstrap_cannot_reach_db(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap_module.settings, "database_url", "postgresql://db.example/db")
    monkeypatch.setattr(bootstrap_module.settings, "db_create_tables_on_startup", True)
    monkeypatch.setattr(bootstrap_module.settings, "environment", "development")
    monkeypatch.setattr(bootstrap_module, "get_engine", lambda: _BrokenEngine())

    with pytest.raises(StartupDatabaseError):
        with TestClient(app):
            pass  # lifespan startup runs the bootstrap and must fail


def test_required_tables_known_entities() -> None:
    assert REQUIRED_TABLES
    assert "reports" in REQUIRED_TABLES
    assert "users" in REQUIRED_TABLES
    assert "priority_results" in REQUIRED_TABLES


def test_postgres_engine_disables_psycopg_prepared_statements(monkeypatch) -> None:
    """Pooler safety: psycopg server-side auto-prepared statements must be off.

    Supabase's session-mode pooler reuses backend sessions that keep prepared
    statement names (``_pg3_0``, ...). A fresh connection's counter restart
    then collides with ``DuplicatePreparedStatement`` and surfaces as an
    intermittent "Database unavailable" during report creation. The rest of
    the codebase already connects with ``prepare_threshold=None``; the app
    engine must match. The engine is built lazily without connecting.
    """
    from sqlalchemy import create_engine as real_create_engine

    captured: dict = {}

    def spy_create_engine(url, **kwargs):
        captured["connect_args"] = kwargs.get("connect_args", {})
        return real_create_engine(url, **kwargs)

    monkeypatch.setattr(db, "create_engine", spy_create_engine)
    monkeypatch.setattr(
        bootstrap_module.settings,
        "database_url",
        "postgresql://user:pass@db.example/app",
    )
    engine = db.get_engine()
    try:
        assert captured["connect_args"].get("prepare_threshold") is None
        assert captured["connect_args"].get("connect_timeout") == 5
    finally:
        db.reset_engine()