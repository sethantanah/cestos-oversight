import pytest
from sqlalchemy import func, select

from app.models import AuditLog, User
from app.tests.conftest import login

pytestmark = pytest.mark.integration


async def superuser_headers(client, admin, session_factory) -> dict[str, str]:
    async with session_factory() as session:
        user = await session.get(User, admin.id)
        assert user is not None
        user.is_superuser = True
        await session.commit()
    tokens = await login(client, admin)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def make_employee(client, headers, **overrides) -> dict:
    body = {"first_name": "Ada", "last_name": "Lovelace", "job_title": "Driller"}
    body.update(overrides)
    response = await client.post("/api/v1/employees", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def make_client(client, headers, name="Acme Mining") -> dict:
    response = await client.post("/api/v1/clients", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def make_project(client, headers, client_id, name="Project Alpha") -> dict:
    response = await client.post(
        "/api/v1/projects", json={"client_id": client_id, "name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_location(client, headers, name="Site A", **overrides) -> dict:
    body: dict = {"name": name, "location_type": "PROJECT_SITE"}
    body.update(overrides)
    response = await client.post("/api/v1/locations", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def make_category(client, headers, name="Diamond Drill Rig") -> dict:
    response = await client.post("/api/v1/asset-categories", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def make_asset(client, headers, category_id, name="CDR-001") -> dict:
    response = await client.post(
        "/api/v1/assets",
        json={"category_id": category_id, "name": name, "meter_type": "ENGINE_HOURS"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_employee_crud_and_numbers(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created = await make_employee(client, headers)
    assert created["employee_number"] == "EMP-000001"
    second = await make_employee(
        client, headers, first_name="Grace", last_name="Hopper", job_title="Mechanic"
    )
    assert second["employee_number"] == "EMP-000002"

    fetched = await client.get(f"/api/v1/employees/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["job_title"] == "Driller"

    updated = await client.patch(
        f"/api/v1/employees/{created['id']}",
        json={"job_title": "Senior Driller"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["job_title"] == "Senior Driller"

    listed = await client.get("/api/v1/employees?search=lovelace", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    paged = await client.get("/api/v1/employees?page=1&page_size=1", headers=headers)
    assert paged.status_code == 200
    body = paged.json()
    assert body["total"] == 2 and body["pages"] == 2 and len(body["items"]) == 1


async def test_employee_organization_isolation(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created = await make_employee(client, headers)
    # Org-B superuser passes permission checks but must not see org-A records.
    other_headers = await superuser_headers(client, identities["other"], session_factory)
    assert (
        await client.get(f"/api/v1/employees/{created['id']}", headers=other_headers)
    ).status_code == 404


async def test_client_project_location_flow(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    assert created_client["client_number"] == "CLI-000001"
    project = await make_project(client, headers, created_client["id"])
    assert project["project_number"] == "PRJ-000001"
    site = await make_location(client, headers, project_id=project["id"])
    assert site["location_number"] == "SITE-000001"

    sites = await client.get(f"/api/v1/projects/{project['id']}/sites", headers=headers)
    assert sites.status_code == 200
    assert [s["id"] for s in sites.json()] == [site["id"]]

    filtered = await client.get(
        f"/api/v1/projects?client_id={created_client['id']}&status=PLANNING", headers=headers
    )
    assert filtered.json()["total"] == 1


async def test_project_rejects_foreign_client(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    other_headers = await superuser_headers(client, identities["other"], session_factory)
    foreign = await make_client(client, other_headers, name="Foreign Co")
    response = await client.post(
        "/api/v1/projects",
        json={"client_id": foreign["id"], "name": "Sneaky"},
        headers=headers,
    )
    assert response.status_code == 404


async def test_asset_flow_and_search(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    assert asset["asset_number"] == "AST-000001"

    updated = await client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"status": "OPERATING", "serial_number": "SN-123"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "OPERATING"

    found = await client.get("/api/v1/assets?search=SN-123", headers=headers)
    assert found.json()["total"] == 1
    by_status = await client.get("/api/v1/assets?status=OPERATING", headers=headers)
    assert by_status.json()["total"] == 1


async def test_employee_assignment_lifecycle(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"])
    site = await make_location(client, headers, project_id=project["id"])

    assignment = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/assignments",
            json={
                "project_id": project["id"],
                "location_id": site["id"],
                "start_date": "2025-06-01",
            },
            headers=headers,
        )
    ).json()
    assert assignment["assignment_number"] == "ASN-000001"

    conflict = await client.post(
        f"/api/v1/employees/{employee['id']}/assignments",
        json={"project_id": project["id"], "start_date": "2025-06-02"},
        headers=headers,
    )
    assert conflict.status_code == 409

    bad_dates = await client.post(
        f"/api/v1/employees/{employee['id']}/assignments",
        json={
            "project_id": project["id"],
            "start_date": "2025-06-10",
            "end_date": "2025-06-01",
            "status": "PLANNED",
        },
        headers=headers,
    )
    assert bad_dates.status_code == 422

    completed = await client.patch(
        f"/api/v1/employee-assignments/{assignment['id']}",
        json={"status": "COMPLETED", "end_date": "2025-07-01"},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"

    history = await client.get(f"/api/v1/employees/{employee['id']}/assignments", headers=headers)
    assert len(history.json()) == 1

    # A new assignment is allowed once the previous one is completed.
    retry = await client.post(
        f"/api/v1/employees/{employee['id']}/assignments",
        json={"project_id": project["id"], "start_date": "2025-08-01"},
        headers=headers,
    )
    assert retry.status_code == 201


async def test_asset_assignment_lifecycle(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"])
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])

    assignment = (
        await client.post(
            f"/api/v1/assets/{asset['id']}/assignments",
            json={
                "project_id": project["id"],
                "responsible_employee_id": employee["id"],
                "assigned_at": "2025-06-01T08:00:00Z",
            },
            headers=headers,
        )
    ).json()
    assert assignment["assignment_number"].startswith("ASN-")

    conflict = await client.post(
        f"/api/v1/assets/{asset['id']}/assignments",
        json={"project_id": project["id"], "assigned_at": "2025-06-02T08:00:00Z"},
        headers=headers,
    )
    assert conflict.status_code == 409

    returned = await client.patch(
        f"/api/v1/asset-assignments/{assignment['id']}",
        json={"status": "COMPLETED", "ending_meter": "150.50"},
        headers=headers,
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "COMPLETED"
    assert returned.json()["returned_at"] is not None

    history = await client.get(f"/api/v1/assets/{asset['id']}/assignments", headers=headers)
    assert len(history.json()) == 1


async def test_meter_reading_validation(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])

    first = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "100.00",
            "recorded_at": "2025-06-01T08:00:00Z",
            "reading_type": "ENGINE_HOURS",
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text

    lower = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "90.00",
            "recorded_at": "2025-06-02T08:00:00Z",
            "reading_type": "ENGINE_HOURS",
        },
        headers=headers,
    )
    assert lower.status_code == 422

    no_reason = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "90.00",
            "recorded_at": "2025-06-02T08:00:00Z",
            "reading_type": "ENGINE_HOURS",
            "is_correction": True,
        },
        headers=headers,
    )
    assert no_reason.status_code == 422

    corrected = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "90.00",
            "recorded_at": "2025-06-02T08:00:00Z",
            "reading_type": "ENGINE_HOURS",
            "is_correction": True,
            "notes": "Meter replaced",
        },
        headers=headers,
    )
    assert corrected.status_code == 201


async def test_documents_skills_and_duplicates(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)

    document = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/documents",
            json={"title": "Passport", "document_type": "PASSPORT", "file_url": "https://x/p.pdf"},
            headers=headers,
        )
    ).json()
    assert document["title"] == "Passport"
    documents = await client.get(f"/api/v1/employees/{employee['id']}/documents", headers=headers)
    assert len(documents.json()) == 1

    skill = (
        await client.post("/api/v1/skills", json={"name": "Diamond drilling"}, headers=headers)
    ).json()
    assigned = await client.post(
        f"/api/v1/employees/{employee['id']}/skills",
        json={"skill_id": skill["id"]},
        headers=headers,
    )
    assert assigned.status_code == 201
    duplicate = await client.post(
        f"/api/v1/employees/{employee['id']}/skills",
        json={"skill_id": skill["id"]},
        headers=headers,
    )
    assert duplicate.status_code == 409


async def test_permission_denied(client, identities):
    tokens = await login(client, identities["denied"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (
        await client.post(
            "/api/v1/employees",
            json={"first_name": "No", "last_name": "Perms", "job_title": "Driller"},
            headers=headers,
        )
    ).status_code == 403
    assert (await client.get("/api/v1/employees", headers=headers)).status_code == 403


async def test_audit_records(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"])
    await client.post(
        f"/api/v1/employees/{employee['id']}/assignments",
        json={"project_id": project["id"], "start_date": "2025-06-01"},
        headers=headers,
    )
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "10.00",
            "recorded_at": "2025-06-01T08:00:00Z",
            "reading_type": "ENGINE_HOURS",
        },
        headers=headers,
    )
    async with session_factory() as session:
        actions = set(
            (
                await session.scalars(
                    select(AuditLog.action).where(
                        AuditLog.organization_id == identities["admin"].organization_id
                    )
                )
            ).all()
        )
    assert {"employee.created", "employee.assigned", "asset.meter_recorded"} <= actions


async def test_overviews_and_summary(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    manager = await make_employee(
        client, headers, first_name="Mara", last_name="Manager", job_title="Project Manager"
    )
    worker = await make_employee(client, headers, first_name="Wes", last_name="Worker")
    created_client = await make_client(client, headers)
    project = (
        await client.post(
            "/api/v1/projects",
            json={
                "client_id": created_client["id"],
                "name": "Project Alpha",
                "project_manager_id": manager["id"],
                "status": "ACTIVE",
            },
            headers=headers,
        )
    ).json()
    site = await make_location(client, headers, project_id=project["id"])
    await client.post(
        f"/api/v1/employees/{worker['id']}/assignments",
        json={"project_id": project["id"], "location_id": site["id"], "start_date": "2025-06-01"},
        headers=headers,
    )
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"], name="Rig-9")
    await client.post(
        f"/api/v1/assets/{asset['id']}/assignments",
        json={
            "project_id": project["id"],
            "location_id": site["id"],
            "responsible_employee_id": worker["id"],
            "assigned_at": "2025-06-01T08:00:00Z",
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "42.50",
            "recorded_at": "2025-06-02T08:00:00Z",
            "reading_type": "ENGINE_HOURS",
        },
        headers=headers,
    )

    emp_overview = (
        await client.get(f"/api/v1/employees/{worker['id']}/overview", headers=headers)
    ).json()
    assert emp_overview["current_assignment"]["project_id"] == project["id"]

    asset_overview = (
        await client.get(f"/api/v1/assets/{asset['id']}/overview", headers=headers)
    ).json()
    assert asset_overview["current_assignment"]["project_id"] == project["id"]
    assert asset_overview["responsible_employee"]["id"] == worker["id"]
    assert asset_overview["latest_meter_reading"]["reading"] == "42.50"

    project_overview = (
        await client.get(f"/api/v1/projects/{project['id']}/overview", headers=headers)
    ).json()
    assert project_overview["client"]["id"] == created_client["id"]
    assert project_overview["project_manager"]["id"] == manager["id"]
    assert project_overview["employee_count"] == 1
    assert project_overview["asset_count"] == 1
    assert len(project_overview["sites"]) == 1

    summary = (await client.get("/api/v1/operations/summary", headers=headers)).json()
    assert summary["employees"]["total"] == 2
    assert summary["employees"]["assigned"] == 1
    assert summary["employees"]["unassigned"] == 1
    assert summary["projects"]["active"] == 1
    assert summary["assets"]["total"] == 1
    assert summary["assets"]["unassigned"] == 0


async def test_archive_and_availability(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    assigned_emp = await make_employee(client, headers, first_name="Busy")
    free_emp = await make_employee(client, headers, first_name="Free")
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"])
    await client.post(
        f"/api/v1/employees/{assigned_emp['id']}/assignments",
        json={"project_id": project["id"], "start_date": "2025-06-01"},
        headers=headers,
    )
    unassigned = await client.get("/api/v1/employees?unassigned_only=true", headers=headers)
    ids = {e["id"] for e in unassigned.json()["items"]}
    assert free_emp["id"] in ids and assigned_emp["id"] not in ids

    archived = await client.post(f"/api/v1/employees/{free_emp['id']}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    again = await client.post(f"/api/v1/employees/{free_emp['id']}/archive", headers=headers)
    assert again.status_code == 409

    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    archived_asset = await client.post(f"/api/v1/assets/{asset['id']}/archive", headers=headers)
    assert archived_asset.status_code == 200
    assert (
        await client.post(f"/api/v1/assets/{asset['id']}/archive", headers=headers)
    ).status_code == 409


async def test_audit_count_matches_mutations(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    await make_employee(client, headers)
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.organization_id == identities["admin"].organization_id,
                AuditLog.action == "employee.created",
            )
        )
    assert count == 1
