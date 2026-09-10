from app.tests.conftest import login
from app.tests.test_asset_domain import (
    make_asset,
    make_category,
    make_client_and_project,
    superuser_headers,
)


async def setup(client, identities, session_factory):
    h = await superuser_headers(client, identities["admin"], session_factory)
    category = await make_category(client, h)
    asset = await make_asset(client, h, category["id"])
    _, project = await make_client_and_project(client, h)
    return h, asset, project


async def test_asset_fuel_maintenance_metrics_and_retirement(client, identities, session_factory):
    h, asset, project = await setup(client, identities, session_factory)
    root = "/api/v1/assets/" + asset["id"]
    response = await client.post(
        root + "/fuel-logs",
        headers=h,
        json={"quantity_litres": "25.125", "unit_cost": "1.25", "project_id": project["id"]},
    )
    assert response.status_code == 201, response.text
    assert (
        await client.post(root + "/fuel-logs", headers=h, json={"quantity_litres": "-1"})
    ).status_code == 422
    assert (
        await client.post(
            root + "/fuel-logs",
            headers=h,
            json={"quantity_litres": "1", "project_id": str(identities["other"].id)},
        )
    ).status_code == 404
    response = await client.post(
        root + "/maintenance", headers=h, json={"title": "Service engine", "cost": "50.25"}
    )
    assert response.status_code == 201, response.text
    job = response.json()
    url = root + "/maintenance/" + job["id"] + "/status"
    # Verify OPEN → COMPLETED direct transition is now allowed
    response = await client.post(
        url, headers=h, json={"status": "COMPLETED", "notes": "Done directly"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"
    # Create a second job to test sequential transitions: OPEN → IN_PROGRESS → COMPLETED
    response2 = await client.post(
        root + "/maintenance", headers=h, json={"title": "Tyre rotation", "cost": "20.00"}
    )
    assert response2.status_code == 201, response2.text
    job2 = response2.json()
    url2 = root + "/maintenance/" + job2["id"] + "/status"
    # Retiring is refused while a maintenance job is still open
    assert (
        await client.post(root + "/retire", headers=h, json={"reason": "End of life"})
    ).status_code == 409
    for status in ["IN_PROGRESS", "COMPLETED"]:
        r = await client.post(url2, headers=h, json={"status": status, "notes": "Checked"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status
    # Cannot transition back from COMPLETED
    assert (
        await client.post(url2, headers=h, json={"status": "IN_PROGRESS", "notes": "Reopen"})
    ).status_code == 409
    metrics = (await client.get(root + "/operating-metrics", headers=h)).json()
    assert float(metrics["fuel_litres"]) == 25.125
    assert metrics["maintenance_by_status"] == [{"status": "COMPLETED", "count": 2}]
    response = await client.post(
        root + "/retire", headers=h, json={"reason": "End of service life"}
    )
    assert response.status_code == 200, response.text
    assert not response.json()["is_active"] and response.json()["status"] == "OUT_OF_SERVICE"
    assert (
        await client.post(root + "/fuel-logs", headers=h, json={"quantity_litres": "1"})
    ).status_code == 409
    actions = (await client.get(root + "/activity", headers=h)).json()
    assert any(r["action"] == "asset.retired" for r in actions)
    other = await login(client, identities["other"])
    assert (
        await client.get(
            root + "/fuel-logs", headers={"Authorization": "Bearer " + other["access_token"]}
        )
    ).status_code in {403, 404}


async def test_project_files_notes_comments_and_isolation(client, identities, session_factory):
    h, _, project = await setup(client, identities, session_factory)
    root = "/api/v1/projects/" + project["id"]
    response = await client.post(
        root + "/files",
        headers=h,
        data={"title": "Site briefing", "description": "Daily briefing"},
        files={"file": ("briefing.txt", b"Site briefing text", "text/plain")},
    )
    assert response.status_code == 201, response.text
    file = response.json()
    assert "storage_path" not in file
    response = await client.get(root + "/files/" + file["id"] + "/download", headers=h)
    assert response.status_code == 200 and response.content == b"Site briefing text"
    for kind in ["NOTE", "COMMENT"]:
        response = await client.post(
            root + "/records",
            headers=h,
            json={"record_type": kind, "title": "Team update", "description": "Work completed."},
        )
        assert response.status_code == 201, response.text
    records = (await client.get(root + "/records?page_size=2", headers=h)).json()
    assert records["total"] == 3 and len(records["items"]) == 2
    denied = await login(client, identities["denied"])
    assert (
        await client.post(
            root + "/records",
            headers={"Authorization": "Bearer " + denied["access_token"]},
            json={"title": "No", "description": "No"},
        )
    ).status_code == 403
    other = await login(client, identities["other"])
    assert (
        await client.get(
            root + "/files/" + file["id"] + "/download",
            headers={"Authorization": "Bearer " + other["access_token"]},
        )
    ).status_code in {403, 404}
    assert (
        await client.post(
            root + "/files",
            headers=h,
            data={"title": "Empty"},
            files={"file": ("empty.txt", b"", "text/plain")},
        )
    ).status_code == 422
