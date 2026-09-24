"""Gated integration tests for the Phase 15 SQLAlchemy repositories.

These tests run ONLY when BOTH are true:
  - ``DATABASE_URL`` is set in the environment (or .env)
  - ``RUN_DB_INTEGRATION=1``

Otherwise they skip, so a normal test run never connects to a database. They
exercise the real create -> commit -> retrieve -> update -> retrieve round trip
against a live PostgreSQL/Supabase instance, using the same SQLAlchemy session
factory as the application. The Phase 15 tables must already exist
(database/migrations/002_app_tables.sql). ``pgvector`` is NOT required
for these tests.

Tests clean up only the rows they create.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env from project root (two levels above database/tests/)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_RUN_BY_REQUEST = os.environ.get("RUN_DB_INTEGRATION", "") == "1"

pytestmark = [
    pytest.mark.skipif(
        not (_DATABASE_URL.strip() and _RUN_BY_REQUEST),
        reason="set DATABASE_URL and RUN_DB_INTEGRATION=1 to run",
    ),
]

from sqlalchemy import delete  # noqa: E402

from app.ai.schemas import NeedCategory, SeverityLevel  # noqa: E402
from app.core.database import get_session_factory, reset_engine  # noqa: E402
from app.location.schemas import LocationStatus  # noqa: E402
from app.models.db_models import ReportRow  # noqa: E402
from app.models.report import Report, ReportStatus  # noqa: E402
from app.repositories.postgres_repositories import (  # noqa: E402
    PostgresReportRepository,
)
from app.verification.schemas import VerificationStatus  # noqa: E402


@pytest.fixture(scope="module")
def report_repository():
    factory = get_session_factory()
    yield PostgresReportRepository(factory)
    reset_engine()


def _unique_report_id() -> str:
    return f"phase15-it-{uuid.uuid4().hex[:12]}"


def test_report_create_commit_retrieve_update_round_trip(report_repository) -> None:
    report_id = _unique_report_id()
    original = Report(
        id=report_id,
        original_text="500 families require clean drinking water immediately",
        reporter="integration_runner",
        timestamp=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        location="Kozhikode",
        incident="Flood",
        evidence=["damage reported by site team"],
        status=ReportStatus.RECEIVED,
        source="integration_test",
        needs=[NeedCategory.WATER, NeedCategory.FOOD],
        location_status=LocationStatus.CONFIRMED,
        severity=SeverityLevel.HIGH,
        affected_population=500,
        available_needs=[NeedCategory.WATER],
        vulnerability=["children"],
        time_sensitivity="immediate",
        verification_status=VerificationStatus.UNVERIFIED,
        original_extraction={"incident": "Flood"},
    )

    # create -> commit
    report_repository.create(original)

    # retrieve
    loaded = report_repository.get_by_id(report_id)
    assert loaded is not None
    assert loaded.original_text == original.original_text
    assert loaded.needs == [NeedCategory.WATER, NeedCategory.FOOD]
    assert loaded.incident == "Flood"
    assert loaded.affected_population == 500
    assert loaded.verification_status == VerificationStatus.UNVERIFIED

    # update -> retrieve
    updated = original.model_copy(
        update={
            "severity": SeverityLevel.CRITICAL,
            "needs": [NeedCategory.SHELTER],
        }
    )
    report_repository.update(report_id, updated)
    refreshed = report_repository.get_by_id(report_id)
    assert refreshed is not None
    assert refreshed.severity == SeverityLevel.CRITICAL
    assert refreshed.needs == [NeedCategory.SHELTER]
    # original evidence text is never overwritten by an update
    assert refreshed.original_text == original.original_text

    finally_cleanup(report_id)


def finally_cleanup(report_id: str) -> None:
    """Remove only the test's own row (integration tests may clean up).

    ``get_session_factory()`` returns a ``sessionmaker``, so it must be called
    to instantiate a :class:`Session` (report_needs rows cascade with the
    report via ``ON DELETE CASCADE``).
    """
    session = get_session_factory()()
    try:
        session.execute(delete(ReportRow).where(ReportRow.report_id == report_id))
        session.commit()
    finally:
        session.close()