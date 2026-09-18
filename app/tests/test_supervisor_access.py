from datetime import date, timedelta
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Employee, EmployeeAssignment, Permission, Role, User
from app.tests.conftest import login
from app.tests.test_operational import make_client, make_employee, make_project, superuser_headers

pytestmark = pytest.mark.integration


async def test_supervisor_scope_across_employee_surfaces(client, identities, session_factory):
    admin = await superuser_headers(client, identities["admin"], session_factory)
    boss = await make_employee(client, admin, first_name="Supervisor")
    direct = await make_employee(client, admin, first_name="Direct", supervisor_id=boss["id"])
    assigned = await make_employee(client, admin, first_name="Project")
    coworker = await make_employee(client, admin, first_name="Coworker")
    hidden = await make_employee(client, admin, first_name="Unrelated")
    files = {}
    for person in [boss, direct, hidden]:
        upload = await client.post(
            f"/api/v1/employees/{person['id']}/documents/upload", headers=admin,
            data={"document_type": "PASSPORT", "title": person["first_name"] + " passport"},
            files={"file": ("passport.pdf", b"%PDF-1.4 test passport", "application/pdf")},
        )
        assert upload.status_code == 201, upload.text
        files[person["id"]] = upload.json()["file_url"]
    customer = await make_client(client, admin)
    project = await make_project(client, admin, customer["id"])
    assignment = await client.post(
        f"/api/v1/employees/{assigned['id']}/assignments", headers=admin,
        json={"project_id": project["id"], "supervisor_id": boss["id"],
              "start_date": str(date.today()), "status": "ACTIVE"},
    )
    assert assignment.status_code == 201, assignment.text
    coworker_assignment = await client.post(
        f"/api/v1/employees/{coworker['id']}/assignments", headers=admin,
        json={"project_id": project["id"], "start_date": str(date.today()), "status": "ACTIVE"},
    )
    assert coworker_assignment.status_code == 201, coworker_assignment.text
    async with session_factory() as session:
        employee = await session.get(Employee, uuid.UUID(boss["id"]))
        employee.user_id = identities["denied"].id
        user = await session.scalar(select(User).where(User.id == identities["denied"].id)
                                    .options(selectinload(User.roles)))
        codes = ["employees.read_basic", "employees.read_full", "employees.update",
                 "employees.skills.read", "employees.audit.read", "projects.read",
                 "employees.documents.read"]
        grants = []
        for code in codes:
            permission = await session.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code)
                session.add(permission)
            grants.append(permission)
        user.roles = [Role(name="Supervisor", organization_id=user.organization_id,
                           permissions=grants)]
        await session.commit()
    tokens = await login(client, identities["denied"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    response = await client.get("/api/v1/employees", headers=headers)
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()["items"]} == {direct["id"], assigned["id"], coworker["id"]}
    assert response.json()["total"] == 3
    catalog = await client.get("/api/v1/documents?view=all", headers=headers)
    assert catalog.status_code == 200, catalog.text
    assert {row["employee_id"] for row in catalog.json()["items"]} == {boss["id"], direct["id"]}
    assert (await client.get(files[hidden["id"]], headers=headers)).status_code == 404
    assert (await client.get(files[direct["id"]], headers=headers)).status_code == 200
    assert (await client.get(files[boss["id"]], headers=headers)).status_code == 200
    filtered = await client.get("/api/v1/employees?search=Unrelated", headers=headers)
    assert filtered.json()["total"] == 0
    for suffix in ["", "/overview", "/full", "/skills", "/activity"]:
        response = await client.get(f"/api/v1/employees/{hidden['id']}{suffix}", headers=headers)
        assert response.status_code == 404, (suffix, response.text)
    response = await client.patch(f"/api/v1/employees/{hidden['id']}", headers=headers,
                                  json={"first_name": "Changed"})
    assert response.status_code == 404, response.text
    assert (await client.get(f"/api/v1/employees/{direct['id']}", headers=headers)).status_code == 200
    update = await client.patch(f"/api/v1/employees/{direct['id']}", headers=headers,
                                json={"job_title": "Senior Driller"})
    assert update.status_code == 200, update.text
    for employee_id in [direct["id"], assigned["id"]]:
        overview = await client.get(f"/api/v1/employees/{employee_id}/overview", headers=headers)
        assert overview.status_code == 200, overview.text
        assert overview.json()["supervisor_name"] == "Supervisor Lovelace"
    overview = await client.get(f"/api/v1/employees/{hidden['id']}/overview", headers=admin)
    assert overview.json()["supervisor_name"] is None
    assert (await client.get(f"/api/v1/hr/employees/{direct['id']}/salaries", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/hr/me", headers=headers)).status_code == 200
    # The supervisor's own profile does not enter the directory after self-service.
    assert (await client.get("/api/v1/employees", headers=headers)).json()["total"] == 3
    assert (await client.get("/api/v1/employees", headers=admin)).json()["total"] == 5
    # Ended and future assignments do not establish access; direct reporting persists.
    async with session_factory() as session:
        row = await session.get(EmployeeAssignment, uuid.UUID(assignment.json()["id"]))
        row.end_date = date.today() - timedelta(days=1)
        await session.commit()
    assert (await client.get("/api/v1/employees", headers=headers)).json()["total"] == 1
    async with session_factory() as session:
        row = await session.get(EmployeeAssignment, uuid.UUID(assignment.json()["id"]))
        row.end_date = None
        row.start_date = date.today() + timedelta(days=1)
        await session.commit()
    assert (await client.get("/api/v1/employees", headers=headers)).json()["total"] == 1
    # Removing the account/profile link fails closed instead of exposing everyone.
    async with session_factory() as session:
        employee = await session.get(Employee, uuid.UUID(boss["id"]))
        employee.user_id = None
        await session.commit()
    assert (await client.get("/api/v1/employees", headers=headers)).json()["total"] == 0
