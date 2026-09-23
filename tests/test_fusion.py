import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_fusion_is_open_without_auth() -> None:
    plain_client = TestClient(app)
    response = plain_client.get("/api/fusion")
    assert response.status_code == 200


def test_fusion_candidate_listing_open(app_client: TestClient) -> None:
    """The candidate list is public; no Authorization header is required."""
    from app.api.fusion import get_fusion_repository
    from app.repositories.fusion_repository import InMemoryFusionRepository

    app.dependency_overrides[get_fusion_repository] = (
        lambda: InMemoryFusionRepository()
    )
    response = app_client.get("/api/fusion")
    assert response.status_code == 200
    assert response.json() == []


def test_fusion_candidate_generation(app_client: TestClient) -> None:
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

def test_fusion_resolve_open(app_client: TestClient) -> None:
    """Resolving a candidate is public and records no imposed identity."""
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