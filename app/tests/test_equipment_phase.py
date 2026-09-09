import base64
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Permission, Role, User
from app.tests.conftest import login
from app.tests.test_asset_domain import (
    make_asset,
    make_category,
    make_client_and_project,
    superuser_headers,
)

pytestmark = pytest.mark.integration


async def test_transfer_is_atomic_and_preserves_history(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    _, project = await make_client_and_project(client, headers)
    second = (
        await client.post(
            "/api/v1/projects",
            headers=headers,
            json={"client_id": project["client_id"], "name": "Bravo"},
        )
    ).json()
    yard = (
        await client.post(
            "/api/v1/locations", headers=headers, json={"name": "Yard", "location_type": "YARD"}
        )
    ).json()
    root = f"/api/v1/assets/{asset['id']}"
    now = datetime.now(UTC)
    first = await client.post(
        root + "/assignments",
        headers=headers,
        json={
            "project_id": project["id"],
            "location_id": yard["id"],
            "assigned_at": now.isoformat(),
            "starting_meter": "10",
        },
    )
    assert first.status_code == 201, first.text
    conflict = await client.post(
        root + "/assignments",
        headers=headers,
        json={"project_id": project["id"], "assigned_at": now.isoformat()},
    )
    assert conflict.status_code == 409
    bad = await client.post(
        root + "/transfer",
        headers=headers,
        json={
            "project_id": str(identities["other"].id),
            "assigned_at": (now + timedelta(minutes=1)).isoformat(),
            "ending_meter": "11",
        },
    )
    assert bad.status_code == 404, bad.text
    assert (await client.get(root + "/assignments", headers=headers)).json()[0][
        "status"
    ] == "ACTIVE"
    result = await client.post(
        root + "/transfer",
        headers=headers,
        json={
            "project_id": second["id"],
            "location_id": yard["id"],
            "assigned_at": (now + timedelta(minutes=2)).isoformat(),
            "ending_meter": "12",
            "starting_meter": "12",
        },
    )
    assert result.status_code == 200, result.text
    rows = (await client.get(root + "/assignments", headers=headers)).json()
    assert sorted(r["status"] for r in rows) == ["ACTIVE", "COMPLETED"]
    assert next(r for r in rows if r["status"] == "COMPLETED")["ending_meter"] == "12.00"
    assert len((await client.get(root + "/location-history", headers=headers)).json()) >= 2
    overview = (await client.get(root + "/overview", headers=headers)).json()
    assert overview["current_project"]["id"] == second["id"]
    assert not overview["is_deployable"]
    assert any(
        r["action"] == "asset.transferred"
        for r in (await client.get(root + "/activity", headers=headers)).json()
    )


async def test_hierarchies_replacement_and_eligibility(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    parent = await make_category(client, headers)
    child = (
        await client.post(
            "/api/v1/asset-categories",
            headers=headers,
            json={"name": "Child", "parent_category_id": parent["id"]},
        )
    ).json()
    assert (
        await client.patch(
            "/api/v1/asset-categories/" + parent["id"],
            headers=headers,
            json={"parent_category_id": child["id"]},
        )
    ).status_code == 422
    asset = await make_asset(client, headers, child["id"])
    root = f"/api/v1/assets/{asset['id']}"
    component = (
        await client.post(
            root + "/components", headers=headers, json={"name": "Engine", "serial_number": "OLD"}
        )
    ).json()
    result = await client.post(
        "/api/v1/asset-components/" + component["id"] + "/replace",
        headers=headers,
        json={"name": "Engine", "serial_number": "NEW"},
    )
    assert result.status_code == 200, result.text
    rows = (await client.get(root + "/components", headers=headers)).json()
    assert {r["serial_number"] for r in rows} == {"OLD", "NEW"}
    assert next(r for r in rows if r["serial_number"] == "OLD")["status"] == "REPLACED"
    defect = (
        await client.post(
            root + "/defects",
            headers=headers,
            json={"severity": "CRITICAL", "description": "Hydraulic leak"},
        )
    ).json()
    assert (await client.get(root + "/overview", headers=headers)).json()[
        "operational_eligibility"
    ] == "NOT_ELIGIBLE"
    assert (await client.get("/api/v1/assets/available", headers=headers)).json()["total"] == 0
    assert (
        await client.post(
            "/api/v1/asset-defects/" + defect["id"] + "/resolve",
            headers=headers,
            json={"notes": "Inspected and repaired"},
        )
    ).status_code == 200
    assert (await client.get("/api/v1/assets/available", headers=headers)).json()["total"] == 1


async def test_financial_visibility_and_meter_override(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"], purchase_price="99999")
    async with session_factory() as session:
        user = await session.get(User, identities["denied"].id)
        await session.refresh(user, ["roles"])
        permissions = []
        for code in ["assets.read", "assets.record_meter"]:
            permission = await session.scalar(select(Permission).where(Permission.code == code))
            permissions.append(permission or Permission(code=code))
        user.roles = [
            Role(
                name="Equipment operator",
                organization_id=user.organization_id,
                permissions=permissions,
            )
        ]
        await session.commit()
    own = {"Authorization": f"Bearer {(await login(client, identities['denied']))['access_token']}"}
    root = f"/api/v1/assets/{asset['id']}"
    for path in [root, root + "/overview", "/api/v1/assets", "/api/v1/assets/dashboard-summary"]:
        result = await client.get(path, headers=own)
        assert result.status_code == 200, result.text
        assert "99999" not in result.text
    now = datetime.now(UTC)
    result = await client.post(
        root + "/meter-readings",
        headers=own,
        json={"reading": "10", "recorded_at": now.isoformat(), "reading_type": "ENGINE_HOURS"},
    )
    assert result.status_code == 201, result.text
    result = await client.post(
        root + "/meter-readings",
        headers=own,
        json={
            "reading": "1",
            "recorded_at": (now + timedelta(seconds=1)).isoformat(),
            "reading_type": "ENGINE_HOURS",
            "is_adjustment": True,
            "adjustment_reason": "Reset",
        },
    )
    assert result.status_code == 403
    result = await client.post(
        root + "/meter-reset",
        headers=headers,
        json={
            "old_reading": "10",
            "new_reading": "1",
            "recorded_at": (now + timedelta(seconds=2)).isoformat(),
            "reason": "Replaced meter",
            "meter_replaced": True,
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["previous_reading"] == "10.00"
    assert result.json()["meter_replaced"]


async def test_photo_primary_and_compliance_links(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    other_asset = await make_asset(client, headers, category["id"], name="Other")
    root = f"/api/v1/assets/{asset['id']}"
    photo = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1sAAAAASUVORK5CYII="
    )
    result = await client.post(
        root + "/media/upload", headers=headers, files={"file": ("rig.png", photo, "image/png")}
    )
    assert result.status_code == 201, result.text
    media = result.json()
    assert (
        await client.post("/api/v1/asset-media/" + media["id"] + "/set-primary", headers=headers)
    ).status_code == 200
    assert (await client.get(root + "/overview", headers=headers)).json()["asset"][
        "profile_photo_url"
    ] == media["file_url"]
    assert (await client.get(media["file_url"], headers=headers)).content == photo
    foreign = (
        await client.post(
            f"/api/v1/assets/{other_asset['id']}/documents",
            headers=headers,
            json={
                "title": "Insurance",
                "document_type": "INSURANCE",
                "file_url": "https://example.com/policy.pdf",
            },
        )
    ).json()
    result = await client.post(
        root + "/insurance",
        headers=headers,
        json={
            "provider": "Example insurer",
            "policy_number": "P1",
            "start_date": "2026-01-01",
            "expiry_date": "2027-01-01",
            "document_id": foreign["id"],
        },
    )
    assert result.status_code == 404, result.text
