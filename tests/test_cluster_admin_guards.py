"""Phase 16 bug-fix regression tests.

Covers the Phase 16 fixes:

1. ``GET /api/clusters`` (list and detail) crash with a ``ValueError`` (500)
   whenever a report's free-text ``location`` contains "::" — the cluster key
   is ``f"{location}::{need}"`` and the old ``key.split("::")`` unpacked the
   extra segments. The key is now split with ``rsplit("::", 1)`` so only the
   final (need) segment is peeled off and a separator inside the location is
   preserved.
2. The final-admin lockout guard falsely rejected an ADMIN demoting an
   already-inactive ADMIN account when only one active admin remained, even
   though the actor stays an active admin (no lockout could occur). The guard
   now only applies to currently-active admin targets, matching its intent.
"""

from datetime import datetime, timezone
from hashlib import md5

import pytest
from fastapi.testclient import TestClient

from app.ai.schemas import NeedCategory, SeverityLevel
from app.models.report import Report
from app.models.user import UserRole
from app.repositories import InMemoryReportRepository, InMemoryUserRepository
from app.schemas.auth import UserUpdate
from app.services.auth_service import AuthService, SelfModificationError
from app.services.cluster_service import ClusterService


def _report(report_id: str, **overrides) -> Report:
    values = {
        "id": report_id,
        "original_text": f"Report {report_id}",
        "reporter": "team_a",
        "timestamp": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        "location": "Kozhikode",
        "evidence": ["bridge washed away"],
        "needs": [NeedCategory.WATER],
        "severity": SeverityLevel.HIGH,
    }
    values.update(overrides)
    return Report(**values)


def _admin(user_id: str, username: str, *, is_active: bool = True):
    from app.models.user import User, UserRole

    return User(
        user_id=user_id,
        username=username,
        password_hash="not-a-real-hash",
        full_name=username,
        role=UserRole.ADMIN,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# Bug 1: "::" inside a free-text location must not crash cluster service
# ---------------------------------------------------------------------------


def test_cluster_location_containing_separator_does_not_crash() -> None:
    repo = InMemoryReportRepository()
    repo.create(
        _report("r-0001", location="Camp Sector::North", needs=[NeedCategory.WATER])
    )
    repo.create(
        _report("r-0002", location="Camp Sector::North", needs=[NeedCategory.WATER])
    )
    clusters = ClusterService(repo).get_clusters()
    assert len(clusters) == 1
    assert clusters[0].location == "Camp Sector::North"
    assert clusters[0].need == "Water"
    assert clusters[0].observations == 2


def test_cluster_separator_in_location_keeps_locations_distinct() -> None:
    """Two distinct "::"-containing locations stay separate clusters."""
    repo = InMemoryReportRepository()
    repo.create(
        _report("r-0001", location="Camp Sector::North", needs=[NeedCategory.WATER])
    )
    repo.create(
        _report("r-0002", location="Camp Sector::South", needs=[NeedCategory.WATER])
    )
    clusters = ClusterService(repo).get_clusters()
    assert sorted(c.location for c in clusters) == [
        "Camp Sector::North",
        "Camp Sector::South",
    ]


def test_clusters_api_returns_200_with_separator_location() -> None:
    """The full ``GET /api/clusters`` path returns 200, not a 500."""
    from app.api.clusters import get_cluster_service
    from app.main import app

    repo = InMemoryReportRepository()
    repo.create(
        _report("r-0001", location="Camp Sector::North", needs=[NeedCategory.WATER])
    )
    app.dependency_overrides[get_cluster_service] = lambda: ClusterService(
        repo
    )
    try:
        with TestClient(app) as client:
            resp = client.get("/api/clusters")
            assert resp.status_code == 200, resp.text
            assert resp.json()["count"] == 1
            assert resp.json()["results"][0]["location"] == "Camp Sector::North"

            # detail lookup uses the same cluster derivation and must not crash
            key = "Camp Sector::North::WATER"
            cluster_id = "NEX-" + md5(key.encode()).hexdigest()[:6].upper()
            detail = client.get(f"/api/clusters/{cluster_id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["location"] == "Camp Sector::North"
    finally:
        app.dependency_overrides.pop(get_cluster_service, None)


# ---------------------------------------------------------------------------
# Bug 2: final-admin guard must not reject demoting an INACTIVE admin
# ---------------------------------------------------------------------------


def test_admin_can_demote_inactive_admin_as_sole_active_admin() -> None:
    repo = InMemoryUserRepository()
    service = AuthService(repo)
    repo.create_user(_admin("a-1", "active-admin"))
    repo.create_user(_admin("a-2", "retired-admin", is_active=False))

    updated = service.update_user(
        "a-2", UserUpdate(role=UserRole.VIEWER), actor_id="a-1"
    )
    assert updated.role == UserRole.VIEWER
    # The actor remains an active admin, so no lockout ever happened.
    actor = service.get_by_id("a-1")
    assert actor.role == UserRole.ADMIN
    assert actor.is_active


def test_admin_can_demote_other_active_admin_when_two_exist() -> None:
    """Unchanged behavior: with two active admins the other may be demoted."""
    repo = InMemoryUserRepository()
    service = AuthService(repo)
    repo.create_user(_admin("a-1", "admin-a"))
    repo.create_user(_admin("a-2", "admin-b"))
    updated = service.update_user(
        "a-2", UserUpdate(role=UserRole.VIEWER), actor_id="a-1"
    )
    assert updated.role == UserRole.VIEWER
    assert service.get_by_id("a-1").role == UserRole.ADMIN


def test_self_demotion_still_rejected() -> None:
    repo = InMemoryUserRepository()
    service = AuthService(repo)
    repo.create_user(_admin("a-1", "admin-a"))
    with pytest.raises(SelfModificationError):
        service.update_user(
            "a-1", UserUpdate(role=UserRole.VIEWER), actor_id="a-1"
        )