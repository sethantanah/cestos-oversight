import pytest

from app.tests.test_operational import (
    make_asset,
    make_category,
    make_client,
    make_employee,
    make_location,
    make_project,
    superuser_headers,
)
from app.tests.test_workforce import make_department, make_position

pytestmark = pytest.mark.integration


async def test_skills_crud_and_assignment(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    skill = (
        await client.post(
            "/api/v1/skills",
            json={"name": "Diamond Drilling", "category": "Drilling"},
            headers=headers,
        )
    ).json()
    updated = await client.patch(
        f"/api/v1/skills/{skill['id']}",
        json={"category": " rigs ".strip() or "Drilling"},
        headers=headers,
    )
    assert updated.status_code == 200
    employee = await make_employee(client, headers)
    link = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/skills",
            json={"skill_id": skill["id"], "proficiency_level": "ADVANCED", "years_experience": 5},
            headers=headers,
        )
    ).json()
    assert link["proficiency_level"] == "ADVANCED" and link["skill_name"] == "Diamond Drilling"
    patched = await client.patch(
        f"/api/v1/employee-skills/{link['id']}",
        json={"proficiency_level": "EXPERT"},
        headers=headers,
    )
    assert patched.json()["proficiency_level"] == "EXPERT"
    assert (
        await client.delete(f"/api/v1/employee-skills/{link['id']}", headers=headers)
    ).status_code == 204
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}/skills", headers=headers)
    ).json() == []
    by_skill = await client.get(f"/api/v1/employees?skill_id={skill['id']}", headers=headers)
    assert by_skill.json()["total"] == 0


async def test_training_and_compliance(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    record = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/training",
            json={
                "training_name": "HSE Induction",
                "provider": "Cestos Academy",
                "start_date": "2026-01-05",
                "completion_date": "2026-01-07",
                "status": "COMPLETED",
                "expiry_date": "2026-09-20",
            },
            headers=headers,
        )
    ).json()
    assert (
        await client.patch(
            f"/api/v1/employee-training/{record['id']}", json={"score": "94.50"}, headers=headers
        )
    ).status_code == 200
    bad = await client.post(
        f"/api/v1/employees/{employee['id']}/training",
        json={"training_name": "Bad", "start_date": "2026-02-01", "completion_date": "2026-01-01"},
        headers=headers,
    )
    assert bad.status_code == 422
    expiring = (await client.get("/api/v1/training/expiring?days=30", headers=headers)).json()
    assert {t["training"]["id"] for t in expiring} >= {record["id"]}
    compliance = (await client.get("/api/v1/training/compliance?days=30", headers=headers)).json()
    assert {t["training"]["id"] for t in compliance} >= {record["id"]}


async def test_licenses_and_filters(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    license_ = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/licenses",
            json={
                "license_type": "DRIVERS_LICENSE",
                "license_number": "DL-001",
                "issue_date": "2024-01-01",
                "expiry_date": "2026-09-25",
                "status": "VALID",
            },
            headers=headers,
        )
    ).json()
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}/licenses", headers=headers)
    ).json()[0]["id"] == license_["id"]
    expiring = (
        await client.get("/api/v1/employee-licenses/expiring?days=30", headers=headers)
    ).json()
    assert {item["license"]["id"] for item in expiring} >= {license_["id"]}
    by_license = await client.get("/api/v1/employees?license_type=DRIVERS_LICENSE", headers=headers)
    assert by_license.json()["total"] == 1
    overview = (
        await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=headers)
    ).json()
    assert len(overview["expiring_licenses"]) == 1
    assert overview["compliance"]["status"] in ("WARNING", "NON_COMPLIANT")


async def test_assignment_types_transfer_and_primary_rules(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    created_client = await make_client(client, headers)
    alpha = await make_project(client, headers, created_client["id"], name="Alpha")
    bravo = await make_project(client, headers, created_client["id"], name="Bravo")
    first = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/assignments",
            json={
                "project_id": alpha["id"],
                "start_date": "2026-01-01",
                "assignment_type": "PROJECT",
                "is_primary": True,
            },
            headers=headers,
        )
    ).json()
    assert first["assignment_type"] == "PROJECT" and first["is_primary"] is True
    fetched = (
        await client.get(f"/api/v1/employee-assignments/{first['id']}", headers=headers)
    ).json()
    assert fetched["assignment_number"] == first["assignment_number"]
    # Non-primary second active assignment is allowed.
    relief = await client.post(
        f"/api/v1/employees/{employee['id']}/assignments",
        json={
            "project_id": bravo["id"],
            "start_date": "2026-02-01",
            "assignment_type": "RELIEF",
            "is_primary": False,
        },
        headers=headers,
    )
    assert relief.status_code == 201
    # Primary second active assignment is rejected.
    assert (
        await client.post(
            f"/api/v1/employees/{employee['id']}/assignments",
            json={"project_id": bravo["id"], "start_date": "2026-03-01", "is_primary": True},
            headers=headers,
        )
    ).status_code == 409
    # Transfer completes the old primary and opens the new one atomically.
    moved = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/transfer",
            json={"project_id": bravo["id"], "start_date": "2026-04-01"},
            headers=headers,
        )
    ).json()
    history = (
        await client.get(f"/api/v1/employees/{employee['id']}/assignments", headers=headers)
    ).json()
    by_id = {a["id"]: a for a in history}
    assert by_id[first["id"]]["status"] == "COMPLETED"
    assert by_id[first["id"]]["end_date"] == "2026-04-01"
    assert moved["status"] == "ACTIVE" and moved["is_primary"] is True
    # Complete and cancel endpoints.
    assert (
        await client.post(f"/api/v1/employee-assignments/{moved['id']}/complete", headers=headers)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/employee-assignments/{relief.json()['id']}/cancel", headers=headers
        )
    ).status_code == 200
    final = (
        await client.get(f"/api/v1/employees/{employee['id']}/assignments", headers=headers)
    ).json()
    assert {a["status"] for a in final} == {"COMPLETED", "CANCELLED"}


async def test_rotations_flow(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    pattern = (
        await client.post(
            "/api/v1/rotation-patterns",
            json={"name": "28/14", "days_on": 28, "days_off": 14},
            headers=headers,
        )
    ).json()
    assert (
        await client.patch(
            f"/api/v1/rotation-patterns/{pattern['id']}",
            json={"description": "Standard"},
            headers=headers,
        )
    ).status_code == 200
    employee = await make_employee(client, headers)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"])
    bad = await client.post(
        f"/api/v1/employees/{employee['id']}/rotations",
        json={
            "rotation_pattern_id": pattern["id"],
            "cycle_start_date": "2026-09-01",
            "work_start_date": "2026-09-10",
            "work_end_date": "2026-09-05",
            "off_start_date": "2026-10-01",
            "off_end_date": "2026-10-14",
        },
        headers=headers,
    )
    assert bad.status_code == 422
    rotation = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/rotations",
            json={
                "rotation_pattern_id": pattern["id"],
                "project_id": project["id"],
                "cycle_start_date": "2026-09-01",
                "work_start_date": "2026-09-01",
                "work_end_date": "2026-09-28",
                "off_start_date": "2026-09-29",
                "off_end_date": "2026-10-12",
                "status": "ON_SITE",
            },
            headers=headers,
        )
    ).json()
    assert rotation["rotation_pattern_name"] == "28/14"
    assert (
        len(
            (
                await client.get(f"/api/v1/employees/{employee['id']}/rotations", headers=headers)
            ).json()
        )
        == 1
    )
    by_rotation = await client.get("/api/v1/employees?rotation_status=ON_SITE", headers=headers)
    assert by_rotation.json()["total"] == 1
    overview = (
        await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=headers)
    ).json()
    assert overview["current_rotation"]["id"] == rotation["id"]
    assert overview["availability_status"] == "ASSIGNED"


async def test_asset_authorizations(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    assert (
        await client.post(
            f"/api/v1/employees/{employee['id']}/asset-authorizations",
            json={"authorization_type": "OPERATOR"},
            headers=headers,
        )
    ).status_code == 422
    authorization = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/asset-authorizations",
            json={
                "authorization_type": "OPERATOR",
                "asset_category_id": category["id"],
                "valid_from": "2026-01-01",
                "valid_until": "2027-01-01",
            },
            headers=headers,
        )
    ).json()
    specific = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/asset-authorizations",
            json={"authorization_type": "DRIVER", "asset_id": asset["id"]},
            headers=headers,
        )
    ).json()
    listed = (
        await client.get(
            f"/api/v1/employees/{employee['id']}/asset-authorizations", headers=headers
        )
    ).json()
    assert {a["id"] for a in listed} == {authorization["id"], specific["id"]}
    revoked = await client.post(
        f"/api/v1/employee-asset-authorizations/{specific['id']}/revoke", headers=headers
    )
    assert revoked.json()["status"] == "REVOKED"
    assert (
        await client.patch(
            f"/api/v1/employee-asset-authorizations/{authorization['id']}",
            json={"notes": "Checked annually"},
            headers=headers,
        )
    ).status_code == 200
    overview = (
        await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=headers)
    ).json()
    assert len(overview["asset_authorizations"]) == 2


async def test_availability_dashboard_manpower_compliance(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    department = await make_department(client, headers, name="Drilling")
    position = await make_position(client, headers, title="Driller", department_id=department["id"])
    free = (
        await client.post(
            "/api/v1/employees",
            json={
                "first_name": "Free",
                "last_name": "Hand",
                "department_id": department["id"],
                "position_id": position["id"],
            },
            headers=headers,
        )
    ).json()
    busy = await make_employee(client, headers, first_name="Busy", job_title="Mechanic")
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"])
    await client.post(
        f"/api/v1/employees/{busy['id']}/assignments",
        json={"project_id": project["id"], "start_date": "2026-01-01"},
        headers=headers,
    )
    assert (await client.get(f"/api/v1/employees/{free['id']}", headers=headers)).json()[
        "availability_status"
    ] == "AVAILABLE"
    assert (await client.get(f"/api/v1/employees/{busy['id']}", headers=headers)).json()[
        "availability_status"
    ] == "ASSIGNED"
    assert (
        await client.get("/api/v1/employees?availability_status=AVAILABLE", headers=headers)
    ).json()["total"] == 1
    available = await client.get("/api/v1/employees/available", headers=headers)
    assert available.json()["total"] == 1
    assert available.json()["items"][0]["current_project_id"] is None
    dashboard = (await client.get("/api/v1/employees/dashboard-summary", headers=headers)).json()
    assert dashboard["total_employees"] == 2
    assert dashboard["assigned_employees"] == 1 and dashboard["available_employees"] == 1
    assert dashboard["employees_by_department"]["Drilling"] == 1
    assert dashboard["employees_by_position"]["Driller"] == 1
    assert dashboard["employees_by_project"][project["name"]] == 1
    assert dashboard["employees_without_emergency_contact"] == 2
    assert dashboard["employees_without_current_resume"] == 2
    assert dashboard["employees_missing_required_documents"] == 2
    manpower = (
        await client.get(f"/api/v1/projects/{project['id']}/manpower-summary", headers=headers)
    ).json()
    assert manpower["total_assigned"] == 1
    assert manpower["by_department"] == [] or isinstance(manpower["by_department"], list)
    assert len(manpower["relief_staff"]) == 1
    assert manpower["relief_staff"][0]["id"] == free["id"]
    # Expired licence drives NON_COMPLIANT.
    await client.post(
        f"/api/v1/employees/{busy['id']}/licenses",
        json={
            "license_type": "DRIVERS_LICENSE",
            "license_number": "X",
            "expiry_date": "2020-01-01",
            "status": "VALID",
        },
        headers=headers,
    )
    overview = (
        await client.get(f"/api/v1/employees/{busy['id']}/overview", headers=headers)
    ).json()
    assert overview["compliance"]["status"] == "NON_COMPLIANT"
    assert any(i["rule"] == "expired_licence" for i in overview["compliance"]["issues"])


async def test_expiry_and_contract_filters(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    expiring_emp = (
        await client.post(
            "/api/v1/employees",
            json={"first_name": "Ex", "last_name": "Piring", "contract_end_date": "2026-09-25"},
            headers=headers,
        )
    ).json()
    await client.post(
        f"/api/v1/employees/{expiring_emp['id']}/documents",
        json={"title": "Permit", "file_url": "https://x/p.pdf", "expiry_date": "2026-09-20"},
        headers=headers,
    )
    by_doc = await client.get("/api/v1/employees?document_expiring_within_days=30", headers=headers)
    assert by_doc.json()["total"] == 1
    by_contract = await client.get(
        "/api/v1/employees?contract_expiring_within_days=30", headers=headers
    )
    assert by_contract.json()["total"] == 1
    sorted_ = await client.get(
        "/api/v1/employees?sort_by=employee_number&sort_dir=desc", headers=headers
    )
    numbers = [item["employee_number"] for item in sorted_.json()["items"]]
    assert numbers == sorted(numbers, reverse=True)
    await make_employee(client, headers, first_name="Other")
    site = await make_location(client, headers, name="Nowhere")
    assert "SITE-" in site["location_number"]
