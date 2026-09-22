import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_fusion_requires_auth() -> None:
    # Use plain client
    plain_client = TestClient(app)
    response = plain_client.get("/api/fusion")
    assert response.status_code == 401

def test_fusion_resolve_requires_reviewer(app_client: TestClient, viewer_headers: dict) -> None:
    app_client.headers.update(viewer_headers)
    response = app_client.post(
        "/api/fusion/FUS-POS-1234/resolve",
        json={"action": "MERGED"}
    )
    assert response.status_code == 403


def test_fusion_candidate_listing_requires_reviewer(
    app_client: TestClient, viewer_headers: dict
) -> None:
    """The candidate list links report ids and similarity evidence: it is the
    reviewer's workspace, not an open read for ANY authenticated user."""
    app_client.headers.update(viewer_headers)
    assert app_client.get("/api/fusion").status_code == 403


def test_fusion_candidate_detail_requires_reviewer(
    app_client: TestClient, viewer_headers: dict
) -> None:
    app_client.headers.update(viewer_headers)
    assert app_client.get("/api/fusion/FC-0001").status_code == 403


def test_fusion_candidate_listing_allows_reviewer(
    app_client: TestClient, reviewer_headers: dict
) -> None:
    from app.api.fusion import get_fusion_repository
    from app.repositories.fusion_repository import InMemoryFusionRepository

    app.dependency_overrides[get_fusion_repository] = (
        lambda: InMemoryFusionRepository()
    )
    app_client.headers.update(reviewer_headers)
    response = app_client.get("/api/fusion")
    assert response.status_code == 200
    assert response.json() == []

def test_fusion_candidate_generation(app_client: TestClient, admin_headers: dict) -> None:
    app_client.headers.update(admin_headers)
    # Create report 1
    r1 = app_client.post(
        "/api/reports",
        json={
            "original_text": "This is exactly the same report text that will trigger duplicate",
            "reporter": "team_a",
            "location": "Test Loc",
            "needs": ["WATER"]
        }
    )
    assert r1.status_code == 201

    # Create report 2
    r2 = app_client.post(
        "/api/reports",
        json={
            "original_text": "This is exactly the same report text that will trigger duplicate",
            "reporter": "team_a",
            "location": "Test Loc",
            "needs": ["WATER"]
        }
    )
    assert r2.status_code == 201

    # Check fusion candidates
    response = app_client.get("/api/fusion")
    assert response.status_code == 200
    cands = response.json()
    
    assert len(cands) >= 1
    assert any(c["type"] == "POSSIBLE_DUPLICATE" for c in cands)
    reasons = " ".join([c.get("reason", "") for c in cands])
    assert "same reporter" in reasons or "text similarity" in reasons
    
def test_fusion_resolve(app_client: TestClient, admin_headers: dict) -> None:
    app_client.headers.update(admin_headers)
    response = app_client.get("/api/fusion")
    cands = [c for c in response.json() if c["status"] == "PENDING"]
    if not cands:
        return
    
    cand_id = cands[0]["id"]
    res = app_client.post(
        f"/api/fusion/{cand_id}/resolve",
        json={"action": "MERGED"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "RESOLVED"
    assert res.json()["resolution"] == "MERGED"
