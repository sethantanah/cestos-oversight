import uuid
import pytest
from datetime import date

from app.core.security import create_access_token
from app.models.user import User
from app.tests.test_operational import (
    make_asset,
    make_category,
    make_client,
    make_employee,
    make_project,
    superuser_headers,
)

pytestmark = pytest.mark.integration


async def test_drilling_program_and_hole_crud(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Gold Exploration Project")

    # 1. Create Program
    program_res = await client.post(
        "/api/v1/drilling/programs",
        json={
            "project_id": project["id"],
            "name": "Phase 1 Resource Definition",
            "code": "PROG-001",
            "target_metres": 5000.0,
            "start_date": "2026-01-15",
            "description": "Deep coring program targeting gold mineralization.",
        },
        headers=headers,
    )
    assert program_res.status_code == 201, program_res.text
    program = program_res.json()
    assert program["name"] == "Phase 1 Resource Definition"
    assert program["status"] == "PLANNING"

    # List Programs
    list_prog = await client.get(f"/api/v1/drilling/programs?project_id={project['id']}", headers=headers)
    assert list_prog.status_code == 200
    assert len(list_prog.json()) == 1

    # 2. Create Drill Hole
    hole_res = await client.post(
        "/api/v1/drilling/holes",
        json={
            "project_id": project["id"],
            "program_id": program["id"],
            "hole_number": "DH-001",
            "drilling_method": "Diamond Core HQ",
            "target_depth_m": 450.0,
            "azimuth_deg": 180.0,
            "dip_deg": -60.0,
        },
        headers=headers,
    )
    assert hole_res.status_code == 201, hole_res.text
    hole = hole_res.json()
    assert hole["hole_number"] == "DH-001"
    assert hole["status"] == "PLANNED"

    # Re-creating same hole number in same project fails
    dup_hole = await client.post(
        "/api/v1/drilling/holes",
        json={
            "project_id": project["id"],
            "program_id": program["id"],
            "hole_number": "DH-001",
        },
        headers=headers,
    )
    assert dup_hole.status_code == 400


async def test_drilling_shift_report_lifecycle_and_summary(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Dugbe Project")

    category = await make_category(client, headers, name="Diamond Core Rig")
    rig = await make_asset(client, headers, category["id"], name="TD900 Core Drill Rig")

    employee = await make_employee(client, headers, first_name="Juah", last_name="Sackie", job_title="Senior Driller")

    # Create Program & Hole
    program = (
        await client.post(
            "/api/v1/drilling/programs",
            json={
                "project_id": project["id"],
                "name": "Dugbe Core Drilling 2026",
                "target_metres": 3000.0,
            },
            headers=headers,
        )
    ).json()

    hole = (
        await client.post(
            "/api/v1/drilling/holes",
            json={
                "project_id": project["id"],
                "program_id": program["id"],
                "hole_number": "DGB-01",
                "drilling_method": "Diamond Core HQ",
                "target_depth_m": 300.0,
            },
            headers=headers,
        )
    ).json()

    # 1. Create Shift Report (Draft)
    shift_res = await client.post(
        "/api/v1/drilling/shifts",
        json={
            "project_id": project["id"],
            "rig_id": rig["id"],
            "program_id": program["id"],
            "date": "2026-03-01",
            "shift_type": "DAY",
            "supervisor_id": employee["id"],
            "notes": "Day shift coring in competent granite.",
            "intervals": [
                {
                    "drill_hole_id": hole["id"],
                    "from_depth_m": 0.0,
                    "to_depth_m": 45.0,
                    "core_recovered_m": 43.5,
                    "drilling_method": "Diamond Core HQ",
                    "ground_conditions": "Hard granite",
                },
                {
                    "drill_hole_id": hole["id"],
                    "from_depth_m": 45.0,
                    "to_depth_m": 90.0,
                    "core_recovered_m": 44.1,
                    "drilling_method": "Diamond Core HQ",
                    "ground_conditions": "Competent quartz-veined granite",
                },
            ],
            "time_segments": [
                {
                    "category": "PRODUCTIVE",
                    "reason_code": "DRILLING",
                    "hours": 9.5,
                    "comments": "Normal drilling operations",
                },
                {
                    "category": "STANDBY",
                    "reason_code": "WATER_HAULAGE",
                    "hours": 1.5,
                    "comments": "Waiting for bowser water delivery",
                },
                {
                    "category": "MAINTENANCE",
                    "reason_code": "HOSE_REPLACEMENT",
                    "hours": 1.0,
                    "comments": "Replaced hydraulic feed line hose",
                },
            ],
            "crew_members": [
                {
                    "employee_id": employee["id"],
                    "role_on_shift": "Senior Driller",
                    "hours_worked": 12.0,
                }
            ],
        },
        headers=headers,
    )
    assert shift_res.status_code == 201, shift_res.text
    shift = shift_res.json()
    assert shift["status"] in ["DRAFT", "SUBMITTED"]
    assert shift["total_metres"] == 90.0
    assert shift["total_productive_hours"] == 9.5
    assert shift["total_nonproductive_hours"] == 2.5
    assert shift["avg_core_recovery_pct"] == 97.33  # (87.6 / 90.0) * 100

    # 2. Test Idempotency Conflict Check: Duplicate shift for same rig + date + shift_type fails
    dup_shift = await client.post(
        "/api/v1/drilling/shifts",
        json={
            "project_id": project["id"],
            "rig_id": rig["id"],
            "date": "2026-03-01",
            "shift_type": "DAY",
        },
        headers=headers,
    )
    err_msg = dup_shift.json().get("error", {}).get("message") or dup_shift.json().get("detail", "")
    assert "already exists" in err_msg

    # 3. State Transition: Submit Shift Report
    submitted = await client.post(
        f"/api/v1/drilling/shifts/{shift['id']}/submit",
        json={"notes": "Submitted for supervisor signoff."},
        headers=headers,
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"

    # 4. State Transition: Return Shift Report for Correction
    returned = await client.post(
        f"/api/v1/drilling/shifts/{shift['id']}/return",
        json={"reason": "Please check maintenance comments."},
        headers=headers,
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "RETURNED"
    assert returned.json()["return_reason"] == "Please check maintenance comments."

    # Resubmit
    resubmitted = await client.post(
        f"/api/v1/drilling/shifts/{shift['id']}/submit",
        json={"notes": "Corrected maintenance comments."},
        headers=headers,
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["status"] == "SUBMITTED"

    # 5. State Transition: Approve Shift Report
    approved = await client.post(
        f"/api/v1/drilling/shifts/{shift['id']}/approve",
        json={"notes": "Approved after verification."},
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    # Verify drill hole depth updated
    updated_hole = (await client.get(f"/api/v1/drilling/holes/{hole['id']}", headers=headers)).json()
    assert updated_hole["status"] == "IN_PROGRESS"
    assert updated_hole["final_depth_m"] == 90.0

    # 6. Verify Project Drilling Summary Endpoint
    summary_res = await client.get(f"/api/v1/drilling/projects/{project['id']}/summary", headers=headers)
    assert summary_res.status_code == 200, summary_res.text
    summary = summary_res.json()
    assert summary["total_programs"] == 1
    assert summary["total_holes"] == 1
    assert summary["active_holes"] == 1
    assert summary["total_shifts_approved"] == 1
    assert summary["total_metres_drilled"] == 90.0
    assert summary["total_productive_hours"] == 9.5
    assert summary["total_standby_hours"] == 1.5
    assert summary["total_maintenance_hours"] == 1.0
    assert summary["overall_avg_core_recovery_pct"] == 97.33


async def test_drilling_shift_report_supervisor_and_project_assignment_validation(client, identities, session_factory):
    import uuid
    from sqlalchemy import select
    from app.models import Employee, EmployeeAssignment, Role, User
    from app.tests.conftest import login

    admin = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, admin)
    assigned_project = await make_project(client, admin, created_client["id"], name="Assigned Project")
    unassigned_project = await make_project(client, admin, created_client["id"], name="Unassigned Project")

    category = await make_category(client, admin, name="RC Rig Category")
    rig = await make_asset(client, admin, category["id"], name="Rig 101")

    # Setup non-supervisor user
    non_sup_user = identities["denied"]
    non_sup_tokens = await login(client, non_sup_user)
    non_sup_headers = {"Authorization": f"Bearer {non_sup_tokens['access_token']}"}

    # 1. Non-supervisor user attempt -> should fail role check
    res1 = await client.post(
        "/api/v1/drilling/shifts",
        json={
            "project_id": assigned_project["id"],
            "rig_id": rig["id"],
            "date": "2026-04-01",
            "shift_type": "DAY",
        },
        headers=non_sup_headers,
    )
    assert res1.status_code == 400
    msg1 = res1.json().get("error", {}).get("message") or res1.json().get("detail", "")
    assert "supervisor or management role" in msg1

    # Now make the non_sup_user a supervisor by creating an Employee record with job_title="Rig Supervisor"
    created_emp = await make_employee(client, admin, first_name="Test", last_name="Supervisor", job_title="Rig Supervisor")
    emp_id = uuid.UUID(created_emp["id"])
    async with session_factory() as session:
        emp_obj = await session.get(Employee, emp_id)
        if emp_obj:
            emp_obj.user_id = non_sup_user.id
            await session.commit()

    # 2. Supervisor attempt for UNASSIGNED project -> should fail project assignment check
    res2 = await client.post(
        "/api/v1/drilling/shifts",
        json={
            "project_id": unassigned_project["id"],
            "rig_id": rig["id"],
            "date": "2026-04-01",
            "shift_type": "DAY",
        },
        headers=non_sup_headers,
    )
    assert res2.status_code == 400
    msg2 = res2.json().get("error", {}).get("message") or res2.json().get("detail", "")
    assert "not assigned to this project" in msg2

    # 3. Assign supervisor to assigned_project
    async with session_factory() as session:
        assignment = EmployeeAssignment(
            assignment_number="ASN-SUP-01",
            organization_id=non_sup_user.organization_id,
            employee_id=emp_id,
            project_id=assigned_project["id"],
            start_date=date.today(),
            status="ACTIVE",
        )
        session.add(assignment)
        await session.commit()

    # 4. Supervisor attempt for ASSIGNED project -> succeeds
    res3 = await client.post(
        "/api/v1/drilling/shifts",
        json={
            "project_id": assigned_project["id"],
            "rig_id": rig["id"],
            "date": "2026-04-01",
            "shift_type": "DAY",
            "supervisor_id": str(emp_id),
        },
        headers=non_sup_headers,
    )
    assert res3.status_code == 201, res3.text
    assert res3.json()["project_id"] == assigned_project["id"]


@pytest.mark.asyncio
async def test_shift_report_approval_permissions(client, session_factory):
    """Test that report approval enforces permission/role restrictions."""
    org_id = uuid.uuid4()
    regular_user = User(
        id=uuid.uuid4(),
        email=f"regular_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hash",
        organization_id=org_id,
        is_superuser=False,
    )
    async with session_factory() as session:
        session.add(regular_user)
        await session.commit()

    reg_token = create_access_token(data={"sub": regular_user.email, "org_id": str(org_id)})
    reg_headers = {"Authorization": f"Bearer {reg_token}"}

    super_user = User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hash",
        organization_id=org_id,
        is_superuser=True,
    )
    async with session_factory() as session:
        session.add(super_user)
        await session.commit()

    super_token = create_access_token(data={"sub": super_user.email, "org_id": str(org_id)})
    super_headers = {"Authorization": f"Bearer {super_token}"}

    # Superuser creates a project & shift report
    proj_res = await client.post("/api/v1/projects", json={"name": "Approval Test Proj", "code": f"ATP-{uuid.uuid4().hex[:4]}"}, headers=super_headers)
    project = proj_res.json()

    rig_res = await client.post("/api/v1/assets", json={"name": "Approval Test Rig", "category": "RIG", "asset_number": f"RIG-APP-{uuid.uuid4().hex[:4]}"}, headers=super_headers)
    rig = rig_res.json()

    shift_res = await client.post(
        "/api/v1/drilling/shifts",
        json={"project_id": project["id"], "rig_id": rig["id"], "date": "2026-04-05", "shift_type": "NIGHT"},
        headers=super_headers,
    )
    shift = shift_res.json()

    # Regular non-approver user attempts to approve shift report -> 400 rejection
    app_fail = await client.post(f"/api/v1/drilling/shifts/{shift['id']}/approve", json={}, headers=reg_headers)
    assert app_fail.status_code == 400
    msg = app_fail.json().get("error", {}).get("message") or app_fail.json().get("detail", "")
    assert "You do not have permission to approve shift reports" in msg

    # Superuser approves -> succeeds
    app_ok = await client.post(f"/api/v1/drilling/shifts/{shift['id']}/approve", json={}, headers=super_headers)
    assert app_ok.status_code == 200
    assert app_ok.json()["status"] == "APPROVED"


