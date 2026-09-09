import pytest
from datetime import date, datetime, UTC
from sqlalchemy import select

from app.models import User, AuditLog
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


async def user_headers(client, user) -> dict[str, str]:
    tokens = await login(client, user)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def make_category(client, headers, name="Diamond Drill Rig") -> dict:
    res = await client.post("/api/v1/asset-categories", json={"name": name, "description": f"Test {name}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def make_asset(client, headers, category_id, name="CDR-001", meter_type="ENGINE_HOURS", **overrides) -> dict:
    body = {
        "category_id": category_id,
        "name": name,
        "manufacturer": "Sandvik",
        "model": "DE810",
        "serial_number": f"SN-{name}",
        "year_of_manufacture": 2023,
        "meter_type": meter_type,
        "status": "AVAILABLE",
    }
    body.update(overrides)
    res = await client.post("/api/v1/assets", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def make_client_and_project(client, headers) -> tuple[dict, dict]:
    c_res = await client.post("/api/v1/clients", json={"name": "Test Mining Client"}, headers=headers)
    assert c_res.status_code == 201
    c_data = c_res.json()
    p_res = await client.post("/api/v1/projects", json={"client_id": c_data["id"], "name": "Project Alpha"}, headers=headers)
    assert p_res.status_code == 201
    return c_data, p_res.json()


async def test_asset_categories_crud(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat1 = await make_category(client, headers, "RC Drill Rig")
    cat2 = await make_category(client, headers, "Heavy Vehicle")

    res = await client.get("/api/v1/asset-categories", headers=headers)
    assert res.status_code == 200
    categories = res.json()
    names = [c["name"] for c in categories]
    assert "RC Drill Rig" in names
    assert "Heavy Vehicle" in names


async def test_asset_crud_and_overview(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Drill Rig")
    asset = await make_asset(client, headers, cat["id"], name="Rig-101")
    assert asset["asset_number"].startswith("AST-")

    # Get asset
    res = await client.get(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert res.status_code == 200
    assert res.json()["name"] == "Rig-101"

    # Update asset
    patch_res = await client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"notes": "Updated operational notes", "status": "STANDBY"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["notes"] == "Updated operational notes"
    assert patch_res.json()["status"] == "STANDBY"

    # Overview
    ov_res = await client.get(f"/api/v1/assets/{asset['id']}/overview", headers=headers)
    assert ov_res.status_code == 200
    ov = ov_res.json()
    assert ov["asset"]["id"] == asset["id"]
    assert ov["category"]["id"] == cat["id"]

    # List with pagination and search
    list_res = await client.get("/api/v1/assets?search=Rig-101", headers=headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == asset["id"]

    # Archive asset
    arch_res = await client.post(f"/api/v1/assets/{asset['id']}/archive", headers=headers)
    assert arch_res.status_code == 200
    assert arch_res.json()["is_active"] is False


async def test_asset_assignments_lifecycle(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Support Truck")
    asset = await make_asset(client, headers, cat["id"], name="Truck-01")
    _, project = await make_client_and_project(client, headers)

    # Assign asset
    assign_res = await client.post(
        f"/api/v1/assets/{asset['id']}/assignments",
        json={
            "project_id": project["id"],
            "assigned_at": datetime.now(UTC).isoformat(),
            "starting_meter": "100.00",
            "notes": "Initial deployment to site",
        },
        headers=headers,
    )
    assert assign_res.status_code == 201, assign_res.text
    assignment = assign_res.json()
    assert assignment["status"] == "ACTIVE"
    assert assignment["starting_meter"] == "100.00"

    # Query asset assignments
    list_assign = await client.get(f"/api/v1/assets/{asset['id']}/assignments", headers=headers)
    assert list_assign.status_code == 200
    assert len(list_assign.json()) == 1

    # End assignment
    end_res = await client.patch(
        f"/api/v1/asset-assignments/{assignment['id']}",
        json={
            "returned_at": datetime.now(UTC).isoformat(),
            "ending_meter": "250.00",
            "status": "COMPLETED",
        },
        headers=headers,
    )
    assert end_res.status_code == 200
    assert end_res.json()["status"] == "COMPLETED"
    assert end_res.json()["ending_meter"] == "250.00"


async def test_asset_meter_readings(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Generator")
    asset = await make_asset(client, headers, cat["id"], name="Gen-500", meter_type="OPERATING_HOURS")

    # Record first reading
    mr1 = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "50.00",
            "recorded_at": datetime.now(UTC).isoformat(),
            "reading_type": "OPERATING_HOURS",
            "source": "Routine Check",
        },
        headers=headers,
    )
    assert mr1.status_code == 201
    assert mr1.json()["reading"] == "50.00"

    # Record second reading
    mr2 = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "120.50",
            "recorded_at": datetime.now(UTC).isoformat(),
            "reading_type": "OPERATING_HOURS",
            "source": "Shift End",
        },
        headers=headers,
    )
    assert mr2.status_code == 201
    assert mr2.json()["reading"] == "120.50"

    # Monotonicity check (lower reading without correction should fail)
    mr_fail = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "100.00",
            "recorded_at": datetime.now(UTC).isoformat(),
            "reading_type": "OPERATING_HOURS",
        },
        headers=headers,
    )
    assert mr_fail.status_code == 422

    # Correction allows lower reading
    mr_corr = await client.post(
        f"/api/v1/assets/{asset['id']}/meter-readings",
        json={
            "reading": "100.00",
            "recorded_at": datetime.now(UTC).isoformat(),
            "reading_type": "OPERATING_HOURS",
            "is_correction": True,
            "notes": "Meter replaced",
        },
        headers=headers,
    )
    assert mr_corr.status_code == 201

    # List meter readings
    history = await client.get(f"/api/v1/assets/{asset['id']}/meter-readings", headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 3


async def test_asset_components(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Drill Engine Unit")
    asset = await make_asset(client, headers, cat["id"], name="Rig-202")

    comp_res = await client.post(
        f"/api/v1/assets/{asset['id']}/components",
        json={
            "name": "Main Hydraulic Pump",
            "component_type": "Pump",
            "manufacturer": "Bosch Rexroth",
            "model": "A10VSO",
            "status": "INSTALLED",
        },
        headers=headers,
    )
    assert comp_res.status_code == 201
    assert comp_res.json()["name"] == "Main Hydraulic Pump"

    list_comp = await client.get(f"/api/v1/assets/{asset['id']}/components", headers=headers)
    assert list_comp.status_code == 200
    assert len(list_comp.json()) == 1


async def test_asset_documents_and_upload(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Light Vehicle")
    asset = await make_asset(client, headers, cat["id"], name="LV-001")

    # Document metadata entry
    doc_res = await client.post(
        f"/api/v1/assets/{asset['id']}/documents",
        json={
            "document_type": "OTHER",
            "title": "Vehicle Registration Certificate",
            "file_url": "https://storage.example.com/docs/reg.pdf",
            "document_number": "REG-2025-001",
        },
        headers=headers,
    )
    assert doc_res.status_code == 201
    assert doc_res.json()["title"] == "Vehicle Registration Certificate"

    # List documents
    docs = await client.get(f"/api/v1/assets/{asset['id']}/documents", headers=headers)
    assert docs.status_code == 200
    assert len(docs.json()) == 1


async def test_asset_location_history_and_status_changes(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Drill Rig")
    asset = await make_asset(client, headers, cat["id"], name="Rig-303")
    _, project = await make_client_and_project(client, headers)
    loc_res = await client.post("/api/v1/locations", json={"name": "Yard B", "location_type": "YARD"}, headers=headers)
    assert loc_res.status_code == 201
    loc = loc_res.json()

    # Location event
    loc_evt = await client.post(
        f"/api/v1/assets/{asset['id']}/location-events",
        json={
            "location_id": loc["id"],
            "event_type": "TRANSFER",
            "project_id": project["id"],
            "meter_reading": "300.00",
            "notes": "Moved to Yard B",
        },
        headers=headers,
    )
    assert loc_evt.status_code == 201

    loc_hist = await client.get(f"/api/v1/assets/{asset['id']}/location-history", headers=headers)
    assert loc_hist.status_code == 200
    assert len(loc_hist.json()) >= 1

    # Status change
    st_res = await client.post(
        f"/api/v1/assets/{asset['id']}/status",
        json={"new_status": "OPERATING", "reason": "Deployed to field operations"},
        headers=headers,
    )
    assert st_res.status_code == 200
    assert st_res.json()["status"] == "OPERATING"


async def test_asset_insurance_and_registrations(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Pickup")
    asset = await make_asset(client, headers, cat["id"], name="Pickup-88")

    # Add insurance
    ins_res = await client.post(
        f"/api/v1/assets/{asset['id']}/insurance",
        json={
            "provider": "Liberia National Insurance",
            "policy_number": "POL-9901",
            "start_date": "2025-01-01",
            "expiry_date": "2026-01-01",
            "coverage_type": "Comprehensive",
            "premium_amount": 1200.0,
        },
        headers=headers,
    )
    assert ins_res.status_code == 201

    ins_list = await client.get(f"/api/v1/assets/{asset['id']}/insurance", headers=headers)
    assert ins_list.status_code == 200
    assert len(ins_list.json()) == 1

    # Add registration
    reg_res = await client.post(
        f"/api/v1/assets/{asset['id']}/registrations",
        json={
            "registration_type": "Vehicle License",
            "registration_number": "LR-P-8800",
            "issuing_authority": "Ministry of Transport",
            "issue_date": "2025-01-01",
            "expiry_date": "2026-01-01",
        },
        headers=headers,
    )
    assert reg_res.status_code == 201

    reg_list = await client.get(f"/api/v1/assets/{asset['id']}/registrations", headers=headers)
    assert reg_list.status_code == 200
    assert len(reg_list.json()) == 1


async def test_asset_inspections_and_defects(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    cat = await make_category(client, headers, "Heavy Compressor")
    asset = await make_asset(client, headers, cat["id"], name="Comp-900")

    # Create inspection
    insp_res = await client.post(
        f"/api/v1/assets/{asset['id']}/inspections",
        json={
            "inspection_type": "Pre-Operation",
            "condition_status": "DEFECTIVE",
            "summary": "Oil leak detected under pressure valve",
            "defects_found": True,
            "defect_notes": "High priority leak",
            "follow_up_required": True,
        },
        headers=headers,
    )
    assert insp_res.status_code == 201
    insp = insp_res.json()

    insp_list = await client.get(f"/api/v1/assets/{asset['id']}/inspections", headers=headers)
    assert insp_list.status_code == 200
    assert len(insp_list.json()) == 1

    # Report defect
    def_res = await client.post(
        f"/api/v1/assets/{asset['id']}/defects",
        json={
            "severity": "CRITICAL",
            "description": "Critical hydraulic hose rupture risk",
            "inspection_id": insp["id"],
            "notes": "Immediate isolation required",
        },
        headers=headers,
    )
    assert def_res.status_code == 201
    defect = def_res.json()

    # Query critical defects
    crit_res = await client.get("/api/v1/assets/defects/critical", headers=headers)
    assert crit_res.status_code == 200
    crit_ids = [d["id"] for d in crit_res.json()]
    assert defect["id"] in crit_ids

    # Resolve defect
    res_res = await client.post(
        f"/api/v1/assets/{asset['id']}/defects/{defect['id']}/resolve",
        json={"notes": "Replaced hydraulic hose assembly and tested under pressure"},
        headers=headers,
    )
    assert res_res.status_code == 200
    assert res_res.json()["status"] == "RESOLVED"


async def test_asset_organization_isolation(client, identities, session_factory):
    admin_a_headers = await superuser_headers(client, identities["admin"], session_factory)
    admin_b_headers = await superuser_headers(client, identities["other"], session_factory)

    # Org A creates category & asset
    cat_a = await make_category(client, admin_a_headers, "Org A Cat")
    asset_a = await make_asset(client, admin_a_headers, cat_a["id"], name="OrgA-Rig")

    # Org B attempts to access Org A's asset directly -> 404
    get_res = await client.get(f"/api/v1/assets/{asset_a['id']}", headers=admin_b_headers)
    assert get_res.status_code == 404

    # Org B lists assets -> does not see Org A's asset
    list_res = await client.get("/api/v1/assets", headers=admin_b_headers)
    assert list_res.status_code == 200
    ids_b = [a["id"] for a in list_res.json()["items"]]
    assert asset_a["id"] not in ids_b
