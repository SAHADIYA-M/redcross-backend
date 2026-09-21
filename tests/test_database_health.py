"""Regression tests for the Phase 15 database health check.

The health check must reflect the *application engine's* connectivity: the
previous implementation opened a second (probe) pool against the Supabase
pooler, which could be refused with a ConnectionTimeout (pooler connection
budget exhausted by the application pool) while the application itself was
perfectly reachable — so /health reported "degraded" for a healthy database.

These tests run fully offline: reachable cases use a SQLite stand-in for the
shared engine, failure cases stub the engine connect, and /health responses are
asserted to never raise or leak connection details.
"""

import json

import pytest

import app.core.database as db
from app.core.database import DatabaseUnavailableError, check_database_health
from app.main import app


@pytest.fixture(autouse=True)
def _isolate_engine():
    db.reset_engine()
    yield
    db.reset_engine()


class _BrokenEngine:
    """Fake application engine whose connect() fails like an unreachable DB."""

    def connect(self):
        raise DatabaseUnavailableError("database is down")


def _use_sqlite(monkeypatch):
    """Point the app-engine path at a fast, offline (SQLite) stand-in.

    The application engine passes Postgres-pooler kwargs (pool_size,
    max_overflow, pool_timeout) to create_engine; SQLite's default pool
    rejects those, so the test also neutralizes the pool options. This only
    affects the stand-in engine, never production Postgres behavior.
    """
    monkeypatch.setattr(db.settings, "database_url", "sqlite://")
    monkeypatch.setattr(db, "_pool_options", lambda: {})


def test_check_database_health_true_when_application_engine_healthy(monkeypatch):
    # A reachable database (SQLite stands in for PostgreSQL offline) must be
    # reported as healthy through the shared engine path.
    _use_sqlite(monkeypatch)
    assert check_database_health() is True


def test_check_database_health_reuses_shared_engine_no_probe(monkeypatch):
    # The old implementation created a second (probe) engine for the health
    # check. The fix must NOT create any new engine when the shared one exists.
    _use_sqlite(monkeypatch)
    db.get_engine()
    engine_creations = []
    original_create_engine = db.create_engine

    def spy_create_engine(*args, **kwargs):
        engine_creations.append(args)
        return original_create_engine(*args, **kwargs)

    monkeypatch.setattr(db, "create_engine", spy_create_engine)

    assert check_database_health() is True
    assert engine_creations == [], "health check must not spawn its own engine"


def test_check_database_health_false_and_never_raises_when_down(monkeypatch):
    monkeypatch.setattr(db.settings, "database_url", "postgresql://db.example/db")
    monkeypatch.setattr(db, "get_engine", lambda: _BrokenEngine())
    assert check_database_health() is False


def test_check_database_health_false_without_engine_when_not_configured(
    monkeypatch,
):
    # With no DATABASE_URL the check must short-circuit: it must not even
    # attempt to build an engine.
    monkeypatch.setattr(db.settings, "database_url", "")
    monkeypatch.setattr(
        db,
        "get_engine",
        lambda: (_ for _ in ()).throw(AssertionError("engine must not be built")),
    )
    assert check_database_health() is False


def test_health_reports_healthy_when_database_reachable(monkeypatch):
    from fastapi.testclient import TestClient

    _use_sqlite(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "healthy", "database": "healthy"}


def test_health_reports_degraded_safely_when_database_down(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(db.settings, "database_url", "postgresql://db.example/db")
    monkeypatch.setattr(db, "get_engine", lambda: _BrokenEngine())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    # Non-throwing, and only the agreed fields — no connection/credential info.
    assert set(body) == {"status", "database"}
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    serialized = json.dumps(body).lower()
    assert "postgresql" not in serialized
    assert "supabase" not in serialized
    assert "password" not in serialized


def test_health_healthy_without_database_configured(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(db.settings, "database_url", "")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": None}