"""Phase 14 regression tests for the Phase-14 report-update bug fix.

Regression: PATCH /api/reports/{id} used to silently drop explicit ``null``
values (e.g. ``{"severity": null}``), leaving the old claim in place. A
missing claim and a cleared claim are different, and a cleared claim must
never keep influencing anything afterwards. The fix honours explicit nulls
via ``exclude_unset=True``.

These tests lock the intended semantics in:
- explicit null clears the claim;
- PATCH replaces fields in full (no invisible stale values);
- verification state and the immutable extraction snapshot live outside the
  report-update surface and cannot be changed through it;
- invalid enum values for claimed fields still fail loudly (422).
"""


def _create_report(client) -> dict:
    response = client.post(
        "/api/reports",
        json={
            "original_text": (
                "About 500 families near the Kozhikode beach have no clean "
                "drinking water after the flood."
            ),
            "reporter": "field_team_01",
            "location": "kozhikode beach",
            "source": "FIELD_REPORT",
            "needs": ["WATER", "FOOD"],
            "severity": "HIGH",
            "affected_population": 500,
            "vulnerability": ["children", "elderly"],
            "time_sensitivity": "within 24 hours",
            "evidence": ["no clean drinking water since yesterday"],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_explicit_null_clears_a_claim(app_client) -> None:
    report = _create_report(app_client)
    assert report["severity"] == "HIGH"

    cleared = app_client.patch(
        f"/api/reports/{report['id']}", json={"severity": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["severity"] is None

    # The cleared field is gone from the stored report - the old claim did not
    # survive the explicit clear.
    fetched = app_client.get(f"/api/reports/{report['id']}").json()
    assert fetched["severity"] is None


def test_patch_replaces_fields_in_full_without_stale_values(app_client) -> None:
    report = _create_report(app_client)
    assert report["needs"] == ["WATER", "FOOD"]
    assert report["vulnerability"] == ["children", "elderly"]

    replaced = app_client.patch(
        f"/api/reports/{report['id']}",
        json={"needs": ["WATER"], "vulnerability": []},
    )
    assert replaced.status_code == 200
    body = replaced.json()
    assert body["needs"] == ["WATER"]
    assert body["vulnerability"] == []
    # Fields intentionally not sent are untouched.
    assert body["affected_population"] == 500
    assert body["time_sensitivity"] == "within 24 hours"


def test_report_patch_cannot_touch_verification_state(app_client) -> None:
    report = _create_report(app_client)
    assert report["verification_status"] == "UNVERIFIED"

    forged = app_client.patch(
        f"/api/reports/{report['id']}",
        json={
            "verification_status": "VERIFIED",
            "original_extraction": {"hacked": True},
        },
    )
    # These fields are outside the report-update surface: the request is not a
    # 422 (unknown keys are ignored, not rejected), but they can never change
    # the state they pretend to change. The immutable snapshot is reported
    # exactly as captured at creation.
    assert forged.status_code == 200
    body = forged.json()
    assert body["verification_status"] == "UNVERIFIED"
    assert "hacked" not in body["original_extraction"]
    assert body["original_extraction"]["affected_population"] == 500
    assert body["original_extraction"]["severity"] == "HIGH"
    assert body["original_text"].startswith("About 500 families")


def test_invalid_claim_values_still_fail_loudly(app_client) -> None:
    report = _create_report(app_client)
    response = app_client.patch(
        f"/api/reports/{report['id']}", json={"severity": "NOT_A_LEVEL"}
    )
    assert response.status_code == 422


def test_cleared_claim_reflects_in_priority_calculation(app_client) -> None:
    report = _create_report(app_client)
    before = app_client.post(f"/api/reports/{report['id']}/priority").json()
    assert before["severity_score"] == 75.0

    # Clearing the severity claim removes its contribution in any later
    # backend calculation: the neutral default is applied, not the stale claim.
    app_client.patch(f"/api/reports/{report['id']}", json={"severity": None})
    after = app_client.post(f"/api/reports/{report['id']}/priority").json()
    assert after["severity_score"] == 50.0
    assert after["source_values"]["severity"] is None