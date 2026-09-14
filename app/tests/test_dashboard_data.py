from app.models import Asset, AuditLog, Permission, Role, User
from app.models.asset import AssetStatus
from app.tests.conftest import login
from app.tests.test_operational import (
    make_asset,
    make_category,
    make_client,
    make_employee,
    make_project,
    superuser_headers,
)


async def test_dashboard_counts_availability_and_safe_activity(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    customer = await make_client(client, headers)
    assert "profile_photo_url" in customer or "logo_url" in customer
    project = await make_project(client, headers, customer["id"])
    assert (
        await client.patch(
            "/api/v1/projects/" + project["id"], headers=headers, json={"status": "ACTIVE"}
        )
    ).status_code == 200
    await make_employee(client, headers, first_name="Ready")
    assigned = await make_employee(client, headers, first_name="Assigned")
    await make_employee(client, headers, first_name="On leave", employment_status="ON_LEAVE")
    await make_employee(client, headers, first_name="Suspended", employment_status="SUSPENDED")
    response = await client.post(
        "/api/v1/employees/" + assigned["id"] + "/assignments",
        headers=headers,
        json={"project_id": project["id"], "start_date": "2026-01-01"},
    )
    assert response.status_code == 201, response.text
    category = await make_category(client, headers)
    for status in [AssetStatus.AVAILABLE, AssetStatus.OPERATING, AssetStatus.BREAKDOWN]:
        asset = await make_asset(client, headers, category["id"], name=str(status))
        async with session_factory() as session:
            row = await session.get(Asset, asset["id"])
            row.status = status
            await session.commit()
    archived = await make_asset(client, headers, category["id"], name="Archived available asset")
    async with session_factory() as session:
        row = await session.get(Asset, archived["id"])
        row.is_active = False
        await session.commit()
    summary = (await client.get("/api/v1/operations/summary", headers=headers)).json()
    assert summary["active_projects"] == summary["projects"]["active"] == 1
    assert summary["active_employees"] == summary["employees"]["active"] == 2
    assert summary["available_employees"] == 1
    assert summary["employees"]["unassigned"] == 3
    for field in ["operating_assets", "available_assets", "breakdowns"]:
        assert summary[field] == 1
    assert (
        await client.patch(
            "/api/v1/projects/" + project["id"], headers=headers, json={"is_active": False}
        )
    ).status_code == 200
    summary = (await client.get("/api/v1/operations/summary", headers=headers)).json()
    assert summary["active_projects"] == 0
    async with session_factory() as session:
        session.add_all(
            [
                AuditLog(
                    organization_id=identities["admin"].organization_id,
                    actor_user_id=identities["admin"].id,
                    action="project.updated",
                    entity_type="project",
                    new_values={"title": "Visible update", "password_hash": "hidden"},
                ),
                AuditLog(
                    organization_id=identities["admin"].organization_id,
                    actor_user_id=identities["admin"].id,
                    action="user.updated",
                    entity_type="user",
                    new_values={"title": "Hidden account event"},
                ),
                AuditLog(
                    organization_id=identities["other"].organization_id,
                    actor_user_id=identities["other"].id,
                    action="project.updated",
                    entity_type="project",
                    new_values={"title": "Other organization"},
                ),
            ]
        )
        viewer = await session.get(User, identities["denied"].id)
        await session.refresh(viewer, ["roles"])
        role = Role(
            name="Project dashboard reader",
            organization_id=viewer.organization_id,
            permissions=[Permission(code="projects.read")],
        )
        viewer.roles.append(role)
        await session.commit()
    response = await client.get("/api/v1/operations/activity?page_size=100", headers=headers)
    assert response.status_code == 200, response.text
    feed = response.json()
    assert feed["total"] == len(feed["items"])
    visible = next(i for i in feed["items"] if i["details"].get("title") == "Visible update")
    assert visible["author_name"] == "A Admin" and visible["created_at"]
    assert "hidden" not in response.text.lower()
    assert "Other organization" not in response.text
    assert any("Assigned Lovelace" in i["summary"] for i in feed["items"])
    tokens = await login(client, identities["denied"])
    viewer_feed = await client.get(
        "/api/v1/operations/activity", headers={"Authorization": "Bearer " + tokens["access_token"]}
    )
    assert viewer_feed.status_code == 200
    assert all(i["action"].startswith("project.") for i in viewer_feed.json()["items"])
    first = (await client.get("/api/v1/operations/activity?page_size=1", headers=headers)).json()
    second = (
        await client.get("/api/v1/operations/activity?page_size=1&page=2", headers=headers)
    ).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
