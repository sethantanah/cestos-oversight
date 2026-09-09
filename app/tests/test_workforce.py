import pytest
from sqlalchemy import func, select

from app.core.security import hash_password
from app.models import AuditLog, Permission, Role, User
from app.tests.conftest import PASSWORD, login
from app.tests.test_operational import (
    make_employee,
    superuser_headers,
)

pytestmark = pytest.mark.integration


async def make_department(client, headers, name="Drilling"):
    response = await client.post("/api/v1/departments", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def make_position(client, headers, title="Senior Driller", department_id=None):
    body = {"title": title}
    if department_id:
        body["department_id"] = department_id
    response = await client.post("/api/v1/positions", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_departments_positions_and_master_fields(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    department = await make_department(client, headers)
    position = await make_position(client, headers, department_id=department["id"])
    employee = (
        await client.post(
            "/api/v1/employees",
            json={
                "first_name": "Samuel",
                "last_name": "Doe",
                "work_email": "sam.doe@example.com",
                "primary_phone": "+231770000001",
                "department_id": department["id"],
                "position_id": position["id"],
                "job_title": "Senior Driller",
                "gender": "MALE",
                "marital_status": "MARRIED",
                "nationality": "Liberian",
                "hire_date": "2023-01-15",
                "contract_start_date": "2023-01-15",
                "contract_end_date": "2026-01-14",
                "employment_type": "FULL_TIME",
            },
            headers=headers,
        )
    ).json()
    assert employee["department_id"] == department["id"]
    assert employee["position_id"] == position["id"]
    assert employee["work_email"] == "sam.doe@example.com"

    duplicate = await client.post(
        "/api/v1/employees",
        json={"first_name": "Copy", "last_name": "Cat", "work_email": "SAM.DOE@EXAMPLE.COM"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    bad_contract = await client.patch(
        f"/api/v1/employees/{employee['id']}",
        json={"contract_end_date": "2020-01-01"},
        headers=headers,
    )
    assert bad_contract.status_code == 422

    filtered = await client.get(
        f"/api/v1/employees?department_id={department['id']}&position_id={position['id']}"
        "&employment_type=FULL_TIME&sort_by=last_name&sort_dir=desc",
        headers=headers,
    )
    assert filtered.json()["total"] == 1


async def test_archive_restore_and_supervisor_rules(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    boss = await make_employee(client, headers, first_name="Boss")
    worker = await make_employee(client, headers, first_name="Worker")
    linked = await client.patch(
        f"/api/v1/employees/{worker['id']}", json={"supervisor_id": boss["id"]}, headers=headers
    )
    assert linked.status_code == 200
    assert linked.json()["supervisor_id"] == boss["id"]
    self_supervised = await client.patch(
        f"/api/v1/employees/{worker['id']}", json={"supervisor_id": worker["id"]}, headers=headers
    )
    assert self_supervised.status_code == 422
    by_supervisor = await client.get(
        f"/api/v1/employees?supervisor_id={boss['id']}", headers=headers
    )
    assert by_supervisor.json()["total"] == 1

    archived = await client.post(f"/api/v1/employees/{worker['id']}/archive", headers=headers)
    assert archived.status_code == 200
    restored = await client.post(f"/api/v1/employees/{worker['id']}/restore", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["is_active"] is True
    again = await client.post(f"/api/v1/employees/{worker['id']}/restore", headers=headers)
    assert again.status_code == 409


async def test_family_flow_and_summary(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    spouse = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/family",
            json={"full_name": "Jane Doe", "relationship_type": "SPOUSE", "is_next_of_kin": True},
            headers=headers,
        )
    ).json()
    child = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/family",
            json={"full_name": "Junior Doe", "relationship_type": "CHILD", "is_dependent": True},
            headers=headers,
        )
    ).json()
    parent = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/family",
            json={"full_name": "Papa Doe", "relationship_type": "PARENT"},
            headers=headers,
        )
    ).json()
    assert (
        await client.get(f"/api/v1/employee-family-members/{spouse['id']}", headers=headers)
    ).status_code == 200

    await client.post(
        f"/api/v1/employee-family-members/{parent['id']}/set-dependent", headers=headers
    )
    marked = await client.post(
        f"/api/v1/employee-family-members/{spouse['id']}/set-next-of-kin", headers=headers
    )
    assert marked.json()["is_next_of_kin"] is True

    full = (await client.get(f"/api/v1/employees/{employee['id']}/full", headers=headers)).json()
    assert len(full["family"]) == 3
    overview = (
        await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=headers)
    ).json()
    assert overview["family_summary"]["spouse"] == "Jane Doe"
    assert overview["family_summary"]["children_count"] == 1
    assert overview["family_summary"]["dependants_count"] == 2

    archived = await client.post(
        f"/api/v1/employee-family-members/{child['id']}/archive", headers=headers
    )
    assert archived.status_code == 200
    remaining = await client.get(f"/api/v1/employees/{employee['id']}/family", headers=headers)
    assert len(remaining.json()) == 3  # archived rows stay visible with flags
    assert sum(1 for m in remaining.json() if m["is_active"]) == 2


async def test_emergency_contacts_primary_and_link(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    member = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/family",
            json={"full_name": "Kin Person", "relationship_type": "SIBLING"},
            headers=headers,
        )
    ).json()
    first = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/emergency-contacts",
            json={
                "full_name": "Kin Person",
                "primary_phone": "+111",
                "is_primary": True,
                "family_member_id": member["id"],
            },
            headers=headers,
        )
    ).json()
    second = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/emergency-contacts",
            json={"full_name": "Friend", "primary_phone": "+222"},
            headers=headers,
        )
    ).json()
    assert first["family_member_id"] == member["id"]
    await client.post(
        f"/api/v1/employee-emergency-contacts/{second['id']}/set-primary", headers=headers
    )
    contacts = (
        await client.get(f"/api/v1/employees/{employee['id']}/emergency-contacts", headers=headers)
    ).json()
    primaries = [c for c in contacts if c["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["id"] == second["id"]
    primary = (
        await client.get(f"/api/v1/employees/{employee['id']}/emergency-contact", headers=headers)
    ).json()
    assert primary["id"] == second["id"]

    other = await make_employee(client, headers, first_name="Other")
    bad_link = await client.post(
        f"/api/v1/employees/{other['id']}/emergency-contacts",
        json={"full_name": "Wrong", "primary_phone": "+333", "family_member_id": member["id"]},
        headers=headers,
    )
    assert bad_link.status_code == 422


async def test_resume_versioning(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    v1 = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/resumes/upload",
            files={"file": ("cv1.pdf", b"%PDF-1.4 v1", "application/pdf")},
            data={"title": "CV v1"},
            headers=headers,
        )
    ).json()
    assert v1["version"] == 1 and v1["is_current"] is True
    v2 = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/resumes/upload",
            files={"file": ("cv2.pdf", b"%PDF-1.4 v2", "application/pdf")},
            data={"title": "CV v2"},
            headers=headers,
        )
    ).json()
    assert v2["version"] == 2 and v2["is_current"] is True
    current = (
        await client.get(f"/api/v1/employees/{employee['id']}/resume/current", headers=headers)
    ).json()
    assert current["id"] == v2["id"]
    history = (
        await client.get(f"/api/v1/employees/{employee['id']}/resumes", headers=headers)
    ).json()
    assert len(history) == 2
    back = await client.post(f"/api/v1/employee-resumes/{v1['id']}/set-current", headers=headers)
    assert back.json()["is_current"] is True
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}/resume/current", headers=headers)
    ).json()["id"] == v1["id"]
    download = await client.get(
        f"/api/v1/employees/{employee['id']}/resumes/{v2['id']}/download", headers=headers
    )
    assert download.status_code == 200 and download.content == b"%PDF-1.4 v2"
    await client.post(f"/api/v1/employee-resumes/{v2['id']}/archive", headers=headers)
    overview = (
        await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=headers)
    ).json()
    assert overview["current_resume"]["id"] == v1["id"]


async def test_document_verification_and_expiry(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    doc = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/documents",
            json={
                "title": "Work permit",
                "document_type": "WORK_PERMIT",
                "file_url": "https://x/wp.pdf",
                "expiry_date": "2027-01-01",
            },
            headers=headers,
        )
    ).json()
    assert doc["verification_status"] == "PENDING"
    verified = await client.post(f"/api/v1/employee-documents/{doc['id']}/verify", headers=headers)
    assert verified.json()["verification_status"] == "VERIFIED"
    assert verified.json()["verified_by_id"] is not None
    expired = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/documents",
            json={"title": "Old", "file_url": "https://x/o.pdf", "expiry_date": "2020-01-01"},
            headers=headers,
        )
    ).json()
    assert (
        await client.post(f"/api/v1/employee-documents/{expired['id']}/verify", headers=headers)
    ).status_code == 409
    soon = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/documents",
            json={"title": "Soon", "file_url": "https://x/s.pdf", "expiry_date": "2026-09-20"},
            headers=headers,
        )
    ).json()
    expiring = (
        await client.get("/api/v1/employee-documents/expiring?days=30", headers=headers)
    ).json()
    assert {d["document"]["id"] for d in expiring} >= {soon["id"]}
    assert all("employee_number" in d and "days_until_expiry" in d for d in expiring)
    rejected = await client.post(f"/api/v1/employee-documents/{soon['id']}/reject", headers=headers)
    assert rejected.json()["verification_status"] == "REJECTED"
    assert (
        await client.post(f"/api/v1/employee-documents/{soon['id']}/archive", headers=headers)
    ).status_code == 200


async def test_qualifications(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    created = (
        await client.post(
            f"/api/v1/employees/{employee['id']}/qualifications",
            json={
                "qualification_type": "Diploma",
                "qualification_name": "Drilling Technology",
                "institution": "Mining Institute",
                "completion_date": "2020-06-01",
            },
            headers=headers,
        )
    ).json()
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}/qualifications", headers=headers)
    ).json()[0]["id"] == created["id"]
    updated = await client.patch(
        f"/api/v1/employee-qualifications/{created['id']}",
        json={"grade_or_classification": "Distinction"},
        headers=headers,
    )
    assert updated.json()["grade_or_classification"] == "Distinction"
    assert (
        await client.post(
            f"/api/v1/employee-qualifications/{created['id']}/archive", headers=headers
        )
    ).status_code == 200
    overview = (
        await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=headers)
    ).json()
    assert overview["qualifications"] == []


async def test_audit_trail_for_family_and_resume(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    await client.post(
        f"/api/v1/employees/{employee['id']}/family",
        json={"full_name": "Audit Kin", "relationship_type": "PARENT"},
        headers=headers,
    )
    await client.post(
        f"/api/v1/employees/{employee['id']}/resumes/upload",
        files={"file": ("cv.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=headers,
    )
    timeline = (
        await client.get(f"/api/v1/employees/{employee['id']}/activity", headers=headers)
    ).json()
    actions = {entry["action"] for entry in timeline}
    assert {
        "employee.created",
        "employee.family_member_added",
        "employee.resume_uploaded",
    } <= actions
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.organization_id == identities["admin"].organization_id)
        )
    assert count and count >= 3


async def test_limited_role_privacy(client, identities, session_factory):
    """A basic operational role sees lists but not family/full/overview data."""
    async with session_factory() as session:
        permission = Permission(code="employees.read_basic")
        session.add(permission)
        await session.flush()
        role = Role(
            name="Viewer",
            organization_id=identities["admin"].organization_id,
            permissions=[permission],
        )
        viewer = User(
            organization_id=identities["admin"].organization_id,
            email="viewer@example.com",
            password_hash=hash_password(PASSWORD),
            first_name="V",
            last_name="Viewer",
            roles=[role],
        )
        session.add(viewer)
        await session.commit()
    tokens = await login(client, viewer)
    viewer_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    super_headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, super_headers)
    assert (await client.get("/api/v1/employees", headers=viewer_headers)).status_code == 200
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}", headers=viewer_headers)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}/family", headers=viewer_headers)
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=viewer_headers)
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/employees/{employee['id']}/full", headers=viewer_headers)
    ).status_code == 403
