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
    dup = cands[0]
    assert dup["type"] == "POSSIBLE_DUPLICATE"
    assert "text similarity" in dup["reason"]
    assert "same reporter" in dup["reason"]
    
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
