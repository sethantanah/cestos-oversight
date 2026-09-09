import pytest
from sqlalchemy import func, select

from app.models import AuditLog
from app.tests.conftest import login
from app.tests.test_operational import (
    make_asset,
    make_category,
    make_client,
    make_employee,
    make_project,
    superuser_headers,
)

pytestmark = pytest.mark.integration

PDF_BYTES = b"%PDF-1.4 fake-document-bytes for tests"


async def test_employee_upload_and_download(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    response = await client.post(
        f"/api/v1/employees/{employee['id']}/documents/upload",
        files={"file": ("passport.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "PASSPORT", "title": "Passport scan"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["file_name"] == "passport.pdf"
    assert document["mime_type"] == "application/pdf"
    assert document["file_url"].endswith("/download")

    download = await client.get(document["file_url"], headers=headers)
    assert download.status_code == 200
    assert download.content == PDF_BYTES
    assert download.headers["content-type"] == "application/pdf"

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.organization_id == identities["admin"].organization_id,
                AuditLog.action == "employee.document_added",
            )
        )
    assert count == 1


async def test_employee_upload_rejects_bad_extension(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    response = await client.post(
        f"/api/v1/employees/{employee['id']}/documents/upload",
        files={"file": ("run.exe", b"MZ fake", "application/octet-stream")},
        headers=headers,
    )
    assert response.status_code == 422


async def test_employee_upload_rejects_oversize(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    response = await client.post(
        f"/api/v1/employees/{employee['id']}/documents/upload",
        files={"file": ("big.pdf", b"x" * (11 * 1024 * 1024), "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 422


async def test_employee_upload_forbidden(client, identities):
    tokens = await login(client, identities["denied"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    employees = await client.get("/api/v1/employees", headers=headers)
    assert employees.status_code == 403


async def test_employee_download_without_stored_file(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    employee = await make_employee(client, headers)
    created = await client.post(
        f"/api/v1/employees/{employee['id']}/documents",
        json={
            "title": "External reference",
            "document_type": "OTHER",
            "file_url": "https://example.com/external.pdf",
        },
        headers=headers,
    )
    assert created.status_code == 201
    document = created.json()
    download = await client.get(
        f"/api/v1/employees/{employee['id']}/documents/{document['id']}/download",
        headers=headers,
    )
    assert download.status_code == 404


async def test_asset_document_flow(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])

    meta = await client.post(
        f"/api/v1/assets/{asset['id']}/documents",
        json={
            "title": "Manual",
            "document_type": "OTHER",
            "file_url": "https://example.com/manual.pdf",
        },
        headers=headers,
    )
    assert meta.status_code == 201

    uploaded = await client.post(
        f"/api/v1/assets/{asset['id']}/documents/upload",
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"title": "Purchase invoice"},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text

    listed = await client.get(f"/api/v1/assets/{asset['id']}/documents", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    download = await client.get(uploaded.json()["file_url"], headers=headers)
    assert download.status_code == 200
    assert download.content == PDF_BYTES

    overview = await client.get(f"/api/v1/assets/{asset['id']}/overview", headers=headers)
    assert overview.status_code == 200
    assert len(overview.json()["documents"]) == 2


async def test_asset_document_cross_org_isolation(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    other_headers = await superuser_headers(client, identities["other"], session_factory)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    assert (
        await client.get(f"/api/v1/assets/{asset['id']}/documents", headers=other_headers)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/assets/{asset['id']}/documents/upload",
            files={"file": ("x.pdf", PDF_BYTES, "application/pdf")},
            headers=other_headers,
        )
    ).status_code == 404


async def test_full_employee_asset_document_chain(client, identities, session_factory):
    """End-to-end chain: client -> project -> employee+asset -> uploads -> overviews."""
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"])
    assert project["project_number"].startswith("PRJ-")
    employee = await make_employee(client, headers)
    category = await make_category(client, headers)
    asset = await make_asset(client, headers, category["id"])
    for kind, parent_id in (("employees", employee["id"]), ("assets", asset["id"])):
        response = await client.post(
            f"/api/v1/{kind}/{parent_id}/documents/upload",
            files={"file": ("doc.pdf", PDF_BYTES, "application/pdf")},
            headers=headers,
        )
        assert response.status_code == 201, response.text
    emp_overview = await client.get(f"/api/v1/employees/{employee['id']}/overview", headers=headers)
    assert len(emp_overview.json()["skills"]) == 0
    asset_overview = await client.get(f"/api/v1/assets/{asset['id']}/overview", headers=headers)
    assert len(asset_overview.json()["documents"]) == 1
