"""Offline tests for the PostgreSQL (SQLAlchemy 2.x) repositories.

The same ORM mappings are exercised against an in-memory SQLite engine so the
row<->domain round trips, update/delete behavior, search pushdown and the
duplicate-username path can run in CI without a live Supabase database. The
production path uses PostgreSQL with psycopg; nothing here weakens PostgreSQL
behavior (JSON columns and the case-insensitive username index are both
expressible on SQLite).

PostgreSQL-specific behavior that SQLite cannot faithfully model is gated in
``database/tests/test_postgres_integration.py``.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.schemas import NeedCategory, SeverityLevel
from app.audit.schemas import AuditAction, AuditRecord
from app.core.database import DatabaseUnavailableError, translate_sqlalchemy_error
from app.location.schemas import LocationStatus
from app.models.db_models import Base
from app.models.fusion import (
    FusionCandidate,
    FusionResolution,
    FusionStatus,
    FusionType,
)
from app.models.report import Report, ReportStatus
from app.priority.schemas import PriorityLevel, PriorityResult
from app.repositories import InMemoryReportRepository
from app.repositories.postgres_repositories import (
    PostgresAuditRepository,
    PostgresFusionRepository,
    PostgresPriorityResultRepository,
    PostgresReportRepository,
    PostgresResponseRepository,
    PostgresUserRepository,
    PostgresVerificationRepository,
)
from app.response_activity.schemas import ResponseActivity, ResponseStatus
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.search.schemas import SearchQuery
from app.search.service import SearchService
from app.services.auth_service import DuplicateUserError
from app.verification.schemas import (
    VerificationAction,
    VerificationRecord,
    VerificationStatus,
)


def _factory_for(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def factory(engine):
    return _factory_for(engine)


def _report(report_id: str, **overrides) -> Report:
    base = dict(
        id=report_id,
        original_text=f"Report {report_id}",
        reporter="reporter_a",
        timestamp=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        location="Kozhikode",
        incident="Flood",
        evidence=["bridge washed away"],
        status=ReportStatus.RECEIVED,
        source="radio",
        needs=[NeedCategory.WATER, NeedCategory.FOOD],
        location_status=LocationStatus.CONFIRMED,
        severity=SeverityLevel.HIGH,
        affected_population=500,
        infrastructure_status=None,
        available_needs=[NeedCategory.WATER],
        vulnerability=["children"],
        time_sensitivity="immediate",
        verification_status=VerificationStatus.UNVERIFIED,
        original_extraction={"incident": "Flood", "needs": ["WATER", "FOOD"]},
    )
    base.update(overrides)
    return Report(**base)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_report_round_trip(factory) -> None:
    repo = PostgresReportRepository(factory)
    report = _report("r1")
    assert repo.create(report) is report
    loaded = repo.get_by_id("r1")
    assert loaded is not None
    assert loaded.id == "r1"
    assert loaded.original_text == "Report r1"
    assert loaded.needs == [NeedCategory.WATER, NeedCategory.FOOD]
    assert loaded.evidence == ["bridge washed away"]
    assert loaded.incident == "Flood"
    assert loaded.severity == SeverityLevel.HIGH
    assert loaded.affected_population == 500
    assert loaded.verification_status == VerificationStatus.UNVERIFIED
    assert loaded.original_extraction == {
        "incident": "Flood",
        "needs": ["WATER", "FOOD"],
    }
    assert loaded.timestamp == report.timestamp


def test_report_get_all_single_query(factory) -> None:
    repo = PostgresReportRepository(factory)
    repo.create(_report("r1"))
    repo.create(_report("r2", needs=[NeedCategory.SHELTER], severity=None))
    all_reports = repo.get_all()
    assert {r.id for r in all_reports} == {"r1", "r2"}
    r2 = next(r for r in all_reports if r.id == "r2")
    assert r2.needs == [NeedCategory.SHELTER]
    assert r2.severity is None


def test_report_update_preserves_text_and_identity(factory) -> None:
    repo = PostgresReportRepository(factory)
    repo.create(_report("r1", timestamp=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)))
    updated = _report(
        "r1",
        severity=SeverityLevel.CRITICAL,
        needs=[NeedCategory.SHELTER],
        location="Kannur",
    )
    assert repo.update("r1", updated) is updated
    loaded = repo.get_by_id("r1")
    assert loaded is not None
    assert loaded.severity == SeverityLevel.CRITICAL
    assert loaded.needs == [NeedCategory.SHELTER]
    assert loaded.location == "Kannur"
    # original evidence text survives the update and the identity is unchanged
    assert loaded.original_text == "Report r1"
    assert loaded.id == "r1"


def test_report_update_missing_returns_none(factory) -> None:
    repo = PostgresReportRepository(factory)
    assert repo.update("missing", _report("missing")) is None


def test_report_get_cluster_candidates_scopes_to_cluster(factory) -> None:
    """The SQL pushdown only returns reports in the same location+first-need
    cluster, mirroring the in-memory semantics used by fusion analysis."""
    from app.models.report import DEFAULT_CLUSTER_LOCATION, DEFAULT_CLUSTER_NEED

    repo = PostgresReportRepository(factory)
    repo.create(_report("water-kozhikode", location="Kozhikode", needs=[NeedCategory.WATER]))
    repo.create(
        _report("food-kozhikode", location="Kozhikode", needs=[NeedCategory.FOOD])
    )
    repo.create(_report("water-kannur", location="Kannur", needs=[NeedCategory.WATER]))
    repo.create(_report("no-need-kozhikode", location="Kozhikode", needs=[]))
    repo.create(_report("no-location", location=None, needs=[NeedCategory.WATER]))

    water_kozhikode = repo.get_cluster_candidates("Kozhikode", NeedCategory.WATER.value)
    assert {r.id for r in water_kozhikode} == {"water-kozhikode"}

    first_need_wins = repo.get_cluster_candidates("Kozhikode", NeedCategory.FOOD.value)
    assert {r.id for r in first_need_wins} == {"food-kozhikode"}

    no_need = repo.get_cluster_candidates("Kozhikode", DEFAULT_CLUSTER_NEED)
    assert {r.id for r in no_need} == {"no-need-kozhikode"}

    unknown_location = repo.get_cluster_candidates(
        DEFAULT_CLUSTER_LOCATION, NeedCategory.WATER.value
    )
    assert {r.id for r in unknown_location} == {"no-location"}

    other_location = repo.get_cluster_candidates("Kannur", NeedCategory.WATER.value)
    assert {r.id for r in other_location} == {"water-kannur"}


def test_report_get_cluster_candidates_empty_location_parity(factory) -> None:
    """A report with an empty-string location clusters under ``Unknown
    Location`` exactly like a NULL one, mirroring ``Report.cluster_location``
    and the in-memory repository ('' or None both normalize to the same key)."""
    from app.models.report import DEFAULT_CLUSTER_LOCATION

    pg_repo = PostgresReportRepository(factory)
    im_repo = InMemoryReportRepository()
    for repo in (pg_repo, im_repo):
        repo.create(_report("empty", location="", needs=[NeedCategory.WATER]))
        repo.create(_report("null", location=None, needs=[NeedCategory.WATER]))
        repo.create(_report("real", location="Kozhikode", needs=[NeedCategory.WATER]))

    pg_ids = {
        r.id
        for r in pg_repo.get_cluster_candidates(
            DEFAULT_CLUSTER_LOCATION, NeedCategory.WATER.value
        )
    }
    im_ids = {
        r.id
        for r in im_repo.get_cluster_candidates(
            DEFAULT_CLUSTER_LOCATION, NeedCategory.WATER.value
        )
    }
    assert pg_ids == im_ids == {"empty", "null"}

    # sanity: a concrete location is untouched on both backends
    assert {
        r.id
        for r in pg_repo.get_cluster_candidates("Kozhikode", NeedCategory.WATER.value)
    } == {"real"}
    assert {
        r.id
        for r in im_repo.get_cluster_candidates("Kozhikode", NeedCategory.WATER.value)
    } == {"real"}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _make_user(username: str, full_name: str | None = None) -> User:
    return User(
        user_id=f"{username}-id",
        username=username,
        password_hash=hash_password("s3cret-pass"),
        full_name=full_name,
        role=UserRole.VIEWER,
        is_active=True,
        created_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )


def test_user_round_trip(factory) -> None:
    user_repo = PostgresUserRepository(factory)
    user = user_repo.create_user(_make_user("alice", "Alice"))
    assert user_repo.get_by_id(user.user_id) == user
    by_username = user_repo.get_by_username("ALICE")
    assert by_username is not None and by_username.user_id == user.user_id
    assert by_username.password_hash == user.password_hash
    assert by_username.full_name == "Alice"
    assert user_repo.list_users() == [user]


def test_duplicate_username_raises(factory) -> None:
    user_repo = PostgresUserRepository(factory)
    user_repo.create_user(_make_user("alice", "A"))
    with pytest.raises(DuplicateUserError):
        user_repo.create_user(_make_user("ALICE", "B"))


def test_full_name_empty_round_trips_as_none(factory) -> None:
    user_repo = PostgresUserRepository(factory)
    user_repo.create_user(_make_user("bob", None))
    loaded = user_repo.get_by_username("bob")
    assert loaded is not None
    assert loaded.full_name is None


# ---------------------------------------------------------------------------
# Verification / audit
# ---------------------------------------------------------------------------


def test_verification_round_trip(factory) -> None:
    reports = PostgresReportRepository(factory)
    reports.create(_report("r1"))
    repo = PostgresVerificationRepository(factory)
    record = VerificationRecord(
        verification_id="v1",
        report_id="r1",
        action=VerificationAction.APPROVE,
        previous_status=VerificationStatus.UNVERIFIED,
        new_status=VerificationStatus.VERIFIED,
        reviewer_id="user-1",
        reason="field check",
        timestamp=datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc),
        changes={"severity": {"old": "HIGH", "new": "CRITICAL"}},
    )
    assert repo.create(record) is record
    records = repo.get_all()
    assert len(records) == 1
    assert records[0].report_id == "r1"
    assert records[0].action == VerificationAction.APPROVE
    assert records[0].previous_status == VerificationStatus.UNVERIFIED
    assert records[0].new_status == VerificationStatus.VERIFIED
    assert records[0].reviewer_id == "user-1"
    assert records[0].changes["severity"]["new"] == "CRITICAL"


def test_audit_round_trip_and_append_only(factory) -> None:
    reports = PostgresReportRepository(factory)
    reports.create(_report("r1"))
    repo = PostgresAuditRepository(factory)
    record = AuditRecord(
        audit_id="a1",
        report_id="r1",
        action=AuditAction.APPROVE,
        actor_id="user-1",
        timestamp=datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc),
        reason="confirmed on the ground",
        old_value={"severity": "HIGH"},
        new_value={"severity": "CRITICAL"},
    )
    assert repo.create(record) is record
    records = repo.get_all()
    assert [r.audit_id for r in records] == ["a1"]
    assert records[0].actor_id == "user-1"
    assert records[0].new_value == {"severity": "CRITICAL"}
    # Append-only: the interface has no update/delete methods.
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


# ---------------------------------------------------------------------------
# Response activities
# ---------------------------------------------------------------------------


def test_response_round_trip_and_update_preserves_identity(factory) -> None:
    reports = PostgresReportRepository(factory)
    reports.create(_report("r1"))
    repo = PostgresResponseRepository(factory)
    activity = ResponseActivity(
        response_id="res1",
        report_id="r1",
        need=NeedCategory.WATER,
        activity="Deliver drinking water",
        response_status=ResponseStatus.PLANNED,
        timestamp=datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc),
        location="Kozhikode",
        source="team_alpha",
        notes="pallet of bottled water",
        affected_population=200,
    )
    assert repo.create(activity) is activity
    assert repo.get_by_id("res1") == activity

    updated = activity.model_copy(
        update={"response_status": ResponseStatus.IN_PROGRESS, "notes": None}
    )
    assert repo.update("res1", updated) is updated
    loaded = repo.get_by_id("res1")
    assert loaded is not None
    assert loaded.response_id == "res1"
    assert loaded.response_status == ResponseStatus.IN_PROGRESS
    assert loaded.report_id == "r1"
    assert loaded.need == NeedCategory.WATER
    assert loaded.notes is None
    assert len(repo.get_all()) == 1


# ---------------------------------------------------------------------------
# Fusion candidates
# ---------------------------------------------------------------------------


def test_fusion_round_trip(factory) -> None:
    repo = PostgresFusionRepository(factory)
    reports = PostgresReportRepository(factory)
    reports.create(_report("r1"))
    reports.create(_report("r2"))
    candidate = FusionCandidate(
        id="fc1",
        type=FusionType.POSSIBLE_DUPLICATE,
        report_ids=["r1", "r2"],
        cluster_id="c1",
        reason="same incident reported twice",
        similarity=0.91,
        status=FusionStatus.PENDING,
    )
    repo.save(candidate)
    assert repo.get_by_id("fc1") == candidate
    pending = repo.get_pending()
    assert [c.id for c in pending] == ["fc1"]

    candidate.resolution = FusionResolution.KEPT_SEPARATE
    candidate.status = FusionStatus.RESOLVED
    candidate.reviewed_by = "user-1"
    candidate.reviewed_at = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    repo.save(candidate)
    resolved = repo.get_by_id("fc1")
    assert resolved is not None
    assert resolved.status == FusionStatus.RESOLVED
    assert resolved.resolution == FusionResolution.KEPT_SEPARATE
    assert resolved.reviewed_by == "user-1"
    assert repo.get_pending() == []
    assert [c.id for c in repo.get_all()] == ["fc1"]


# ---------------------------------------------------------------------------
# Priority results
# ---------------------------------------------------------------------------


def test_priority_result_round_trip_and_upsert(factory) -> None:
    reports = PostgresReportRepository(factory)
    reports.create(_report("r1", severity=SeverityLevel.CRITICAL))
    repo = PostgresPriorityResultRepository(factory)
    result = PriorityResult(
        report_id="r1",
        severity_score=100.0,
        affected_population_score=75.0,
        vulnerability_score=60.0,
        time_sensitivity_score=100.0,
        evidence_verification_score=40.0,
        final_score=83.5,
        priority_level=PriorityLevel.HIGH,
        calculation_version="1",
        calculated_at=datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
    )
    repo.save(result)
    loaded = repo.get_by_report("r1")
    assert loaded is not None
    assert loaded.report_id == "r1"
    assert loaded.final_score == 83.5
    assert loaded.priority_level == PriorityLevel.HIGH

    raised = result.model_copy(
        update={"final_score": 88.0, "priority_level": PriorityLevel.CRITICAL}
    )
    repo.save(raised)
    refreshed = repo.get_by_report("r1")
    assert refreshed is not None
    assert refreshed.final_score == 88.0
    assert refreshed.priority_level == PriorityLevel.CRITICAL


def test_priority_result_missing_returns_none(factory) -> None:
    repo = PostgresPriorityResultRepository(factory)
    assert repo.get_by_report("nope") is None


def test_priority_result_delete_by_report(factory) -> None:
    reports = PostgresReportRepository(factory)
    reports.create(_report("r1", severity=SeverityLevel.CRITICAL))
    repo = PostgresPriorityResultRepository(factory)
    repo.save(
        PriorityResult(
            report_id="r1",
            severity_score=100.0,
            affected_population_score=75.0,
            vulnerability_score=60.0,
            time_sensitivity_score=100.0,
            evidence_verification_score=40.0,
            final_score=83.5,
            priority_level=PriorityLevel.HIGH,
            calculation_version="1",
            calculated_at=datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
        )
    )
    assert repo.get_by_report("r1") is not None
    repo.delete_by_report("r1")
    assert repo.get_by_report("r1") is None


def test_report_patch_persists_audit_and_priority_postgres(factory) -> None:
    """A PATCH audit record and refreshed priority persist through the ORM.

    Exercises the PostgreSQL repositories against in-memory SQLite so the
    append-only audit write and the priority upsert are proven to round-trip
    through real SQLAlchemy mappings, not just the in-memory store.
    """
    from app.models.user import User, UserRole
    from app.schemas.report import UpdateReport
    from app.services.priority_service import PriorityService, priority_level_for_score
    from app.services.report_service import ReportService

    reports = PostgresReportRepository(factory)
    reports.create(_report("r1", severity=SeverityLevel.LOW))
    audit = PostgresAuditRepository(factory)
    store = PostgresPriorityResultRepository(factory)
    service = ReportService(
        reports,
        audit,
        priority_service=PriorityService(reports, result_store=store),
    )
    actor = User(
        user_id="actor-1",
        username="assessor_user",
        password_hash="not-a-real-hash",
        role=UserRole.ASSESSOR,
    )

    service.update(
        "r1", UpdateReport(severity=SeverityLevel.CRITICAL), actor=actor
    )

    records = audit.get_all()
    assert [record.action for record in records] == [AuditAction.UPDATE_REPORT]
    assert records[0].report_id == "r1"
    assert records[0].actor_id == "actor-1"
    assert records[0].old_value == {"severity": "LOW"}
    assert records[0].new_value == {"severity": "CRITICAL"}

    stored_priority = store.get_by_report("r1")
    assert stored_priority is not None
    assert stored_priority.severity_score == 100.0
    assert stored_priority.priority_level == priority_level_for_score(
        stored_priority.final_score
    )

    # Original evidence still immutable in the database.
    stored_report = reports.get_by_id("r1")
    assert stored_report is not None
    assert stored_report.original_text == "Report r1"


# ---------------------------------------------------------------------------
# Search: SQL pushdown vs in-memory Python path parity
# ---------------------------------------------------------------------------


def _seed_reports(repo) -> None:
    repo.create(
        _report(
            "r1",
            timestamp=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            needs=[NeedCategory.WATER],
        )
    )
    repo.create(
        _report(
            "r2",
            original_text="500 families need food after the floods",
            timestamp=datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc),
            location="Kochi",
            incident="Flood",
            needs=[NeedCategory.FOOD, NeedCategory.SHELTER],
            verification_status=VerificationStatus.VERIFIED,
            status=ReportStatus.IN_REVIEW,
            source="field_assessment",
        )
    )
    repo.create(
        _report(
            "r3",
            original_text="river dam at 100% capacity is unsafe",
            timestamp=datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc),
            location="Kozhikode dam",
            incident="Dam",
            needs=[NeedCategory.INFRASTRUCTURE_SERVICE],
            verification_status=VerificationStatus.UNCERTAIN,
            source="sensor",
        )
    )


SEARCH_QUERIES = [
    SearchQuery(q="water"),
    SearchQuery(q="100% capacity"),
    SearchQuery(need=[NeedCategory.FOOD]),
    SearchQuery(need=[NeedCategory.WATER, NeedCategory.SHELTER]),
    SearchQuery(verification_status=VerificationStatus.VERIFIED),
    SearchQuery(status=ReportStatus.IN_REVIEW),
    SearchQuery(location="dam"),
    SearchQuery(location_status=LocationStatus.CONFIRMED),
    SearchQuery(incident="Flood"),
    SearchQuery(source="sensor"),
    SearchQuery(
        start_time=datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc),
    ),
    SearchQuery(
        q="families",
        need=[NeedCategory.FOOD],
        verification_status=VerificationStatus.VERIFIED,
        status=ReportStatus.IN_REVIEW,
    ),
]


@pytest.mark.parametrize("query", SEARCH_QUERIES, ids=lambda q: "q")
def test_search_sql_parity_with_python_path(
    factory, query: SearchQuery
) -> None:
    sql_repo = PostgresReportRepository(factory)
    in_mem = InMemoryReportRepository()
    _seed_reports(sql_repo)
    _seed_reports(in_mem)

    sql_service = SearchService(repository=sql_repo)
    python_service = SearchService(repository=in_mem)

    sql_ids = {r.id for r in sql_service._candidates_for(query)}
    python_ids = {r.id for r in python_service._candidates_for(query)}
    assert sql_ids == python_ids


def test_search_no_filters_falls_back_and_matches(factory) -> None:
    """A query with no filters must return everything on both paths."""
    sql_repo = PostgresReportRepository(factory)
    in_mem = InMemoryReportRepository()
    _seed_reports(sql_repo)
    _seed_reports(in_mem)
    query = SearchQuery()

    sql_ids = {r.id for r in SearchService(repository=sql_repo)._candidates_for(query)}
    assert sql_ids == {"r1", "r2", "r3"}
    assert sql_ids == {
        r.id for r in SearchService(repository=in_mem)._candidates_for(query)
    }


def _seed_escaping_reports(repo) -> None:
    repo.create(_report(
        "s1",
        original_text="Dam capacity at 5% is unsafe",
        location="Block at 5% slope",
        incident="Flood",
        source="sensor_x",
    ))
    repo.create(_report(
        "s2",
        original_text="Another 55% reading logged",
        location="Block at 55% slope",
        incident="Flood",
        source="sensorX",
    ))
    repo.create(_report(
        "s3",
        original_text="Underscore_check manual log",
        location="North wing",
        incident="Underscore_check",
        source="radio",
    ))
    repo.create(_report(
        "s4",
        original_text="A_B zone marked",
        location="A_B region",
        incident="Underscore check",
        source="sensor",
    ))
    repo.create(_report(
        "s5",
        original_text="A5B zone",
        location="A5B zone",
        incident="Other event",
        source="sensor_1",
    ))
    repo.create(_report(
        "s6",
        original_text="general field report",
        location="Kochi",
        incident="Flood",
        source="field_assessment",
    ))


def test_search_percent_and_underscore_are_literal_everywhere(factory) -> None:
    """% and _ in search text must match LITERALLY on location, incident,
    source and free text - on SQLite exactly like PostgreSQL (no default
    LIKE escape backends). Without escaping, '%' and '_' are wildcards and
    would match far more than the user typed."""
    sql_repo = PostgresReportRepository(factory)
    in_mem = InMemoryReportRepository()
    _seed_escaping_reports(sql_repo)
    _seed_escaping_reports(in_mem)

    cases = [
        (SearchQuery(location="5% slope"), {"s1", "s2"}),
        (SearchQuery(location="A_B"), {"s4"}),
        (SearchQuery(incident="Underscore_check"), {"s3"}),
        (SearchQuery(source="sensor_"), {"s1", "s5"}),
        (SearchQuery(q="5%"), {"s1", "s2"}),
        (SearchQuery(q="underscore"), {"s3"}),
    ]
    for query, expected in cases:
        sql_ids = {
            r.id for r in SearchService(repository=sql_repo)._candidates_for(query)
        }
        python_ids = {
            r.id for r in SearchService(repository=in_mem)._candidates_for(query)
        }
        assert sql_ids == expected, (query, sql_ids)
        assert sql_ids == python_ids, (query, sql_ids, python_ids)


def test_search_underscore_wildcard_cannot_leak_other_reports(factory) -> None:
    """An unescaped '_' would turn 'A_B' into the wildcard 'A?B' and wrongly
    match 'A5B zone'; the escaped query must match only the literal text."""
    sql_repo = PostgresReportRepository(factory)
    _seed_escaping_reports(sql_repo)
    query = SearchQuery(location="A_B")
    sql_ids = {r.id for r in SearchService(repository=sql_repo)._candidates_for(query)}
    assert sql_ids == {"s4"}


# ---------------------------------------------------------------------------
# Shared error mapping doesn't leak raw drivers
# ---------------------------------------------------------------------------


def test_translate_sqlalchemy_error_keeps_generic_message() -> None:
    """Driver errors are mapped to the domain message; internals never leak."""
    from sqlalchemy.exc import SQLAlchemyError

    class _FakeOrig(Exception):
        """Stands in for a psycopg/sqlite driver exception."""

    err = SQLAlchemyError("boom")
    err.orig = _FakeOrig("connection refused: server closed unexpectedly")
    translated = translate_sqlalchemy_error(err)
    assert isinstance(translated, DatabaseUnavailableError)
    assert "Database operation failed" in str(translated)
    assert "connection refused" not in str(translated)