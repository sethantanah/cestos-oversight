import re
from datetime import date

import pytest
from sqlalchemy import select

from app.models import Employee, User
from app.models.hr import EmailDelivery, PasswordSetup
from app.services.hr import reminder_date
from app.services.mail import deliver_one
from app.tests.conftest import PASSWORD, login
from app.tests.conftest import test_settings as make_settings
from app.tests.test_operational import make_employee, superuser_headers


def test_calendar_month_reminders():
    assert reminder_date(date(2028, 3, 31), 1, "MONTHS") == date(2028, 2, 29)
    assert reminder_date(date(2027, 3, 31), 1, "MONTHS") == date(2027, 2, 28)
    assert reminder_date(date(2027, 1, 1), 2, "WEEKS") == date(2026, 12, 18)


@pytest.mark.integration
async def test_account_setup_self_service_and_reset(
    client, identities, session_factory, monkeypatch
):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(
        client, headers, work_email="new.person@example.com", notes="CONFIDENTIAL HR NOTES"
    )
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "new.person@example.com"))
        assert user.setup_required
        user_id = user.id
        settings = make_settings()
        settings.smtp_host = "smtp.test"
        settings.smtp_from = "hr@example.com"
        mail = []
        monkeypatch.setattr("app.services.mail.send_email", lambda *args: mail.append(args))
        assert await deliver_one(session, settings)
        raw = re.search(r"#reset=([\w-]+)", mail[0][3]).group(1)
    result = await client.post(
        "/api/v1/hr/password-reset", json={"token": raw, "password": PASSWORD}
    )
    assert result.status_code == 200, result.text
    assert (
        await client.post("/api/v1/hr/password-reset", json={"token": raw, "password": PASSWORD})
    ).status_code == 401
    async with session_factory() as session:
        user = await session.get(User, user_id)
    tokens = await login(client, user)
    own = {"Authorization": f"Bearer {tokens['access_token']}"}
    profile = await client.get("/api/v1/hr/me", headers=own)
    assert profile.status_code == 200, profile.text
    assert "CONFIDENTIAL" not in profile.text
    assert (
        await client.patch(
            f"/api/v1/employees/{employee['id']}", json={"first_name": "Forbidden"}, headers=own
        )
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/hr/employees/{employee['id']}/salaries", headers=own)
    ).status_code == 403
    response = await client.post(
        f"/api/v1/hr/employees/{employee['id']}/account/reset", headers=headers
    )
    assert response.status_code == 200, response.text
    assert (await client.get("/api/v1/hr/me", headers=own)).status_code == 401
    async with session_factory() as session:
        assert await deliver_one(session, settings)
    reset_token = re.search(r"#reset=([\w-]+)", mail[-1][3]).group(1)
    result = await client.post(
        "/api/v1/hr/password-reset", json={"token": reset_token, "password": PASSWORD}
    )
    assert result.status_code == 200, result.text
    assert (
        await client.post(
            "/api/v1/hr/password-reset", json={"token": reset_token, "password": PASSWORD}
        )
    ).status_code == 401
    async with session_factory() as session:
        user = await session.get(User, user_id)
    tokens = await login(client, user)
    own = {"Authorization": f"Bearer {tokens['access_token']}"}
    response = await client.put(
        f"/api/v1/hr/employees/{employee['id']}/account/email",
        json={"email": "renamed@example.com"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert (await client.get("/api/v1/hr/me", headers=own)).status_code == 401


@pytest.mark.integration
async def test_salary_dates_scope_and_alert_dedup(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    base = f"/api/v1/hr/employees/{employee['id']}/salaries"
    salary = {
        "amount": "1000.00",
        "currency": "USD",
        "pay_period": "MONTHLY",
        "start_date": "2026-01-01",
    }
    first = await client.post(base, json=salary, headers=headers)
    assert first.status_code == 201, first.text
    assert (await client.post(base, json=salary, headers=headers)).status_code == 409
    end = await client.post(
        f"/api/v1/hr/salaries/{first.json()['id']}/end",
        json={"end_date": "2026-08-31"},
        headers=headers,
    )
    assert end.status_code == 200, end.text
    salary["start_date"] = "2026-09-01"
    assert (await client.post(base, json=salary, headers=headers)).status_code == 201
    doc = await client.post(
        f"/api/v1/employees/{employee['id']}/documents",
        json={
            "title": "Contract",
            "document_type": "EMPLOYMENT_CONTRACT",
            "file_url": "https://example.com/contract",
            "expiry_date": date.today().isoformat(),
        },
        headers=headers,
    )
    assert doc.status_code == 201, doc.text
    body = {
        "name": "One calendar month",
        "lead_value": 1,
        "lead_unit": "MONTHS",
        "recipient_ids": [str(identities["admin"].id)],
    }
    rule = await client.post("/api/v1/hr/alert-rules", json=body, headers=headers)
    assert rule.status_code == 201, rule.text
    run = await client.post("/api/v1/hr/alert-rules/run", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["notifications_created"] == 1
    assert (await client.post("/api/v1/hr/alert-rules/run", headers=headers)).json()[
        "notifications_created"
    ] == 0
    assert len((await client.get("/api/v1/hr/notifications", headers=headers)).json()) == 1
    body["recipient_ids"] = [str(identities["other"].id)]
    assert (
        await client.post("/api/v1/hr/alert-rules", json=body, headers=headers)
    ).status_code == 422


@pytest.mark.integration
async def test_existing_account_link_no_privilege_grant(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    user = identities["denied"]
    employee = await make_employee(client, headers, work_email=user.email)
    async with session_factory() as session:
        row = await session.get(Employee, __import__("uuid").UUID(employee["id"]))
        assert row.user_id == user.id
        stored = await session.get(User, user.id)
        assert not stored.setup_required
    tokens = await login(client, user)
    own = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.get("/api/v1/hr/me", headers=own)).status_code == 200
    assert (await client.get("/api/v1/employees", headers=own)).status_code == 403


@pytest.mark.integration
async def test_contract_ownership_and_smtp_retry(client, identities, session_factory, monkeypatch):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers, work_email=identities["denied"].email)
    other_employee = await make_employee(client, headers)

    async def upload(employee_id):
        result = await client.post(
            f"/api/v1/employees/{employee_id}/documents/upload",
            headers=headers,
            data={
                "title": "Employment agreement",
                "document_type": "EMPLOYMENT_CONTRACT",
                "expiry_date": "2027-01-01",
            },
            files={"file": ("agreement.pdf", b"%PDF-1.4\ncontract", "application/pdf")},
        )
        assert result.status_code == 201, result.text
        return result.json()["id"]

    own_document = await upload(employee["id"])
    other_document = await upload(other_employee["id"])
    own = {"Authorization": f"Bearer {(await login(client, identities['denied']))['access_token']}"}
    assert (
        await client.get(f"/api/v1/hr/me/contracts/{own_document}/download", headers=own)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/hr/me/contracts/{other_document}/download", headers=own)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/employee-documents/{own_document}", json={"title": "Tamper"}, headers=own
        )
    ).status_code == 403
    await make_employee(client, headers, work_email="mail.retry@example.com")
    settings = make_settings()
    settings.smtp_host = "smtp.test"
    settings.smtp_from = "hr@example.com"
    import smtplib

    def fail(*args):
        raise smtplib.SMTPException("test")

    monkeypatch.setattr("app.services.mail.send_email", fail)
    async with session_factory() as session:
        assert await deliver_one(session, settings)
        delivery = await session.scalar(select(EmailDelivery).where(EmailDelivery.kind == "SETUP"))
        assert delivery.status == "PENDING" and delivery.attempts == 1
        assert not (await session.scalars(select(PasswordSetup))).all()


@pytest.mark.integration
async def test_cross_tenant_account_and_salary_isolation(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    # Same email in another organization never links across the tenant boundary.
    employee = await make_employee(client, headers, work_email=identities["other"].email)
    async with session_factory() as session:
        row = await session.get(Employee, __import__("uuid").UUID(employee["id"]))
        assert row.user_id == identities["admin"].id
        assert row.user_id != identities["other"].id
    other_headers = await superuser_headers(client, identities["other"], session_factory)
    assert (
        await client.get(f"/api/v1/hr/employees/{employee['id']}/salaries", headers=other_headers)
    ).status_code == 404
    assert (
        await client.put(
            f"/api/v1/hr/employees/{employee['id']}/account/email",
            json={"email": "steal@example.com"},
            headers=other_headers,
        )
    ).status_code == 404


@pytest.mark.integration
async def test_basic_employee_access_redacts_private_master_fields(
    client, identities, session_factory
):
    from app.models import Permission, Role

    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(
        client,
        headers,
        personal_email="private@example.com",
        residential_address="PRIVATE ADDRESS",
        notes="PRIVATE NOTE",
    )
    async with session_factory() as session:
        role = Role(
            organization_id=identities["denied"].organization_id,
            name="Basic workforce reader",
            permissions=[Permission(code="employees.read_basic")],
        )
        user = await session.get(User, identities["denied"].id)
        await session.refresh(user, ["roles"])
        user.roles = [role]
        await session.commit()
    own = {"Authorization": f"Bearer {(await login(client, identities['denied']))['access_token']}"}
    for path in ["/api/v1/employees", f"/api/v1/employees/{employee['id']}"]:
        response = await client.get(path, headers=own)
        assert response.status_code == 200, response.text
        assert (
            "PRIVATE ADDRESS" not in response.text
            and "PRIVATE NOTE" not in response.text
            and "private@example.com" not in response.text
        )


@pytest.mark.integration
async def test_self_service_edits_and_protected_fields(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers, work_email=identities["denied"].email)
    own = {"Authorization": f"Bearer {(await login(client, identities['denied']))['access_token']}"}
    update = await client.patch(
        "/api/v1/hr/me",
        headers=own,
        json={
            "preferred_name": "  AJ  ",
            "primary_phone": "+23112345",
            "residential_address": "New address",
        },
    )
    assert update.status_code == 200, update.text
    profile = (await client.get("/api/v1/hr/me", headers=own)).json()
    assert profile["preferred_name"] == "AJ" and profile["residential_address"] == "New address"
    for key in (
        "employee_id",
        "organization_id",
        "user_id",
        "is_superuser",
        "first_name",
        "work_email",
        "personal_email",
        "employment_status",
        "department_id",
        "salary",
        "contracts",
        "assignments",
        "notes",
        "hire_date",
        "profile_photo_url",
        "qualifications",
        "training",
    ):
        response = await client.patch(
            "/api/v1/hr/me",
            headers=own,
            json={"preferred_name": "Should not save", key: "unauthorized"},
        )
        assert response.status_code == 422, (key, response.text)
    assert (await client.get("/api/v1/hr/me", headers=own)).json()["preferred_name"] == "AJ"
    assert (
        await client.patch("/api/v1/hr/me", headers=own, json={"preferred_name": None})
    ).status_code == 200
    contact = {
        "full_name": "Emergency One",
        "relationship": "Sibling",
        "primary_phone": "12345",
        "address": "Safe address",
        "email": None,
    }
    first = await client.post("/api/v1/hr/me/emergency-contacts", headers=own, json=contact)
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    second = await client.post(
        "/api/v1/hr/me/emergency-contacts",
        headers=own,
        json={**contact, "full_name": "Emergency Two"},
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assert (
        await client.post(f"/api/v1/hr/me/emergency-contacts/{first_id}/archive", headers=own)
    ).status_code == 409
    assert (
        await client.put(
            f"/api/v1/hr/me/emergency-contacts/{second_id}",
            headers=own,
            json={**contact, "full_name": "Updated contact"},
        )
    ).status_code == 200
    assert (
        await client.put(
            f"/api/v1/hr/me/emergency-contacts/{second_id}",
            headers=own,
            json={**contact, "employee_id": employee["id"]},
        )
    ).status_code == 422
    assert (
        await client.post(f"/api/v1/hr/me/emergency-contacts/{second_id}/primary", headers=own)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/hr/me/emergency-contacts/{first_id}/archive", headers=own)
    ).status_code == 200
    contacts = (await client.get("/api/v1/hr/me", headers=own)).json()["emergency_contacts"]
    assert len(contacts) == 1 and contacts[0]["id"] == second_id and contacts[0]["is_primary"]
    another = await make_employee(client, headers)
    foreign = await client.post(
        f"/api/v1/employees/{another['id']}/emergency-contacts", headers=headers, json=contact
    )
    foreign_id = foreign.json()["id"]
    assert (
        await client.put(
            f"/api/v1/hr/me/emergency-contacts/{foreign_id}", headers=own, json=contact
        )
    ).status_code == 404
    for verb in ("primary", "archive"):
        assert (
            await client.post(f"/api/v1/hr/me/emergency-contacts/{foreign_id}/{verb}", headers=own)
        ).status_code == 404
    await client.post(f"/api/v1/employees/{employee['id']}/archive", headers=headers)
    assert (
        await client.patch("/api/v1/hr/me", headers=own, json={"city": "No longer allowed"})
    ).status_code == 404
