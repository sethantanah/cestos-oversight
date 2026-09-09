import pytest
from sqlalchemy import select
from app.models import Employee, User, Role, Permission
from app.tests.conftest import login
from app.tests.test_operational import make_employee, superuser_headers


@pytest.mark.integration
async def test_employee_activity_leave_and_decisions(client, identities, session_factory):
    admin = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, admin, work_email=identities["denied"].email)
    own = {"Authorization": f"Bearer {(await login(client, identities['denied']))['access_token']}"}
    base = "/api/v1/hr/me"
    result = await client.post(f"{base}/time-logs", headers=own, json={"date":"2026-09-08", "notes":"Completed equipment inspection"})
    assert result.status_code == 201, result.text
    assert result.json()["employee_id"] == employee["id"]
    assert len((await client.get(f"{base}/time-logs", headers=own)).json()) == 1
    assert (await client.post(f"{base}/time-logs", headers=own, json={"date":"2026-09-08", "check_in":"2026-09-08T10:00:00Z", "check_out":"2026-09-08T09:00:00Z"})).status_code == 422
    body = {"start_date":"2026-10-01", "end_date":"2026-10-03", "reason":"Family visit"}
    result = await client.post(f"{base}/leave-requests", headers=own, json=body)
    assert result.status_code == 201, result.text
    leave_id = result.json()["id"]
    assert result.json()["status"] == "PENDING"
    assert (await client.post(f"{base}/leave-requests", headers=own, json=body)).status_code == 422
    assert (await client.post(f"{base}/leave-requests", headers=own, json={**body,"end_date":"2026-09-30"})).status_code == 422
    decision = f"/api/v1/employees/{leave_id}/approve"
    assert (await client.patch(decision, headers=own)).status_code == 403
    assert (await client.get(f"/api/v1/employees/{employee['id']}/time-logs", headers=own)).status_code == 403
    other = {"Authorization": f"Bearer {(await login(client, identities['other']))['access_token']}"}
    assert (await client.get(f"{base}/time-logs", headers=other)).status_code == 404
    async with session_factory() as session:
        stored = await session.scalar(select(Employee).where(Employee.user_id==identities['denied'].id))
        assert stored.employment_status == employee['employment_status']
        user = await session.get(User, identities['denied'].id)
        await session.refresh(user, ["roles"])
        user.roles = [Role(name="Leave approver", organization_id=user.organization_id, permissions=[Permission(code="employees.leave.approve")])]
        await session.commit()
    result = await client.patch(decision, headers=own)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "APPROVED"
    assert result.json()["approved_by_id"] == str(identities['denied'].id)
    assert (await client.patch(decision, headers=own)).status_code == 409
    assert (await client.get(f"{base}/leave-requests", headers=own)).json()[0]['status'] == 'APPROVED'


@pytest.mark.integration
async def test_leave_letter_upload_download_and_cleanup(client, identities, session_factory):
    admin = await superuser_headers(client, identities["admin"], session_factory)
    await make_employee(client, admin, work_email=identities["denied"].email)
    own = {"Authorization": f"Bearer {(await login(client, identities['denied']))['access_token']}"}
    body = {"start_date": "2026-11-01", "end_date": "2026-11-03", "reason": "Leave letter attached"}
    files = {"file": ("request.pdf", b"%PDF-1.4 leave letter", "application/pdf")}
    endpoint = "/api/v1/hr/me/leave-requests/upload"
    result = await client.post(endpoint, headers=own, data=body, files=files)
    assert result.status_code == 201, result.text
    url = f"/api/v1/hr/leave-requests/{result.json()['id']}/attachment"
    for headers in (own, admin):
        download = await client.get(url, headers=headers)
        assert download.status_code == 200, download.text
        assert download.content == files['file'][1]
    other = {"Authorization": f"Bearer {(await login(client, identities['other']))['access_token']}"}
    assert (await client.get(url, headers=other)).status_code == 404
    from app.tests.conftest import _TEST_STORAGE
    before = set(_TEST_STORAGE.rglob('*.*'))
    assert (await client.post(endpoint, headers=own, data=body, files=files)).status_code == 422
    assert set(_TEST_STORAGE.rglob('*.*')) == before
    assert (await client.post(endpoint, headers=own, data=body, files={"file":("bad.exe",b"bad")})).status_code == 422
    assert (await client.post(endpoint, headers=own, data=body, files={"file":("empty.pdf",b"")})).status_code == 422
