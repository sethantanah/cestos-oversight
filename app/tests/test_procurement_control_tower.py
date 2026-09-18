import pytest

from app.models.operational_logs import FuelSupplier
from app.tests.test_operational import (
    make_client,
    make_employee,
    make_project,
    superuser_headers,
)

pytestmark = pytest.mark.integration


async def create_supplier(session_factory, org_id):
    async with session_factory() as session:
        supplier = FuelSupplier(
            organization_id=org_id,
            name="Apex Energy & Equipment Ltd",
        )
        session.add(supplier)
        await session.commit()
        await session.refresh(supplier)
        return str(supplier.id)


async def test_procurement_purchase_order_lifecycle_and_receipts(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    org_id = identities["admin"].organization_id

    supplier_id = await create_supplier(session_factory, org_id)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Drilling Ops Project")

    # 1. Create Purchase Order
    po_res = await client.post(
        "/api/v1/procurement/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "project_id": project["id"],
            "currency": "USD",
            "notes": "Urgent procurement of drilling spare parts",
            "items": [
                {
                    "description": "7-1/4 Drill Bit Blades",
                    "quantity_ordered": 10.0,
                    "unit_price": 450.0,
                },
                {
                    "description": "High Pressure Hydraulic Hose 20ft",
                    "quantity_ordered": 5.0,
                    "unit_price": 120.0,
                },
            ],
        },
        headers=headers,
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()
    assert po["po_number"].startswith("PO-")
    assert po["status"] == "APPROVED"
    assert len(po["items"]) == 2
    assert float(po["total_amount"]) == 5100.0

    po_id = po["id"]
    bit_item_id = po["items"][0]["id"]
    hose_item_id = po["items"][1]["id"]

    # 2. Partial Goods Receipt
    recv_res = await client.post(
        f"/api/v1/procurement/purchase-orders/{po_id}/receive",
        json={
            "item_receipts": {
                bit_item_id: 5.0,
            }
        },
        headers=headers,
    )
    assert recv_res.status_code == 200, recv_res.text
    partial_po = recv_res.json()
    assert partial_po["status"] == "PARTIALLY_RECEIVED"

    # 3. Final Goods Receipt to complete
    recv2_res = await client.post(
        f"/api/v1/procurement/purchase-orders/{po_id}/receive",
        json={
            "item_receipts": {
                bit_item_id: 5.0,
                hose_item_id: 5.0,
            }
        },
        headers=headers,
    )
    assert recv2_res.status_code == 200, recv2_res.text
    completed_po = recv2_res.json()
    assert completed_po["status"] == "RECEIVED"


async def test_ceo_control_tower_and_scorecard_calculation(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Takoradi Rig Project")
    supervisor = await make_employee(client, headers, first_name="Samuel", last_name="Quaye", job_title="Rig Supervisor")

    # 1. Create 8-pillar supervisor scorecard (using subscore ceilings: 25, 20, 15, 15, 10, 5, 5, 5)
    sc_res = await client.post(
        "/api/v1/control-tower/scorecards",
        json={
            "supervisor_id": supervisor["id"],
            "project_id": project["id"],
            "period_start": "2026-09-01",
            "period_end": "2026-09-15",
            "production_score": 22.5,
            "rig_condition_score": 18.0,
            "downtime_score": 14.0,
            "hse_score": 15.0,
            "consumables_score": 8.5,
            "crew_management_score": 4.5,
            "reporting_score": 4.5,
            "stewardship_score": 4.0,
            "notes": "Excellent performance across shift cycles.",
        },
        headers=headers,
    )
    assert sc_res.status_code == 201, sc_res.text
    sc = sc_res.json()
    assert sc["scorecard_number"].startswith("SCR-")
    assert float(sc["overall_weighted_score"]) > 85.0
    assert sc["grade"] == "A"

    # 2. Retrieve CEO Control Tower summary
    tower_res = await client.get("/api/v1/control-tower/summary", headers=headers)
    assert tower_res.status_code == 200, tower_res.text
    summary = tower_res.json()
    assert "company_name" in summary
    assert "total_projects" in summary
    assert "active_rigs" in summary
    assert "total_revenue" in summary

    # 3. Retrieve Scorecards List
    sc_list_res = await client.get("/api/v1/control-tower/scorecards", headers=headers)
    assert sc_list_res.status_code == 200, sc_list_res.text
    sc_list = sc_list_res.json()
    assert len(sc_list) >= 1


async def test_commercial_opportunities_and_client_portal(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Offshore Exploration")

    # 1. Create Commercial Opportunity
    opp_res = await client.post(
        "/api/v1/control-tower/opportunities",
        json={
            "client_id": created_client["id"],
            "title": "Deepwater RC Drilling Tender 2026",
            "tender_stage": "PROPOSAL_SENT",
            "win_probability_pct": 75.0,
            "estimated_value": 450000.0,
            "currency": "USD",
            "expected_close_date": "2026-12-31",
            "notes": "Strong client relationship and competitive pricing.",
        },
        headers=headers,
    )
    assert opp_res.status_code == 201, opp_res.text
    opp = opp_res.json()
    assert opp["opportunity_number"].startswith("OPP-")
    assert opp["tender_stage"] == "PROPOSAL_SENT"

    # 2. Grant Client Access to Project
    grant_res = await client.post(
        "/api/v1/control-tower/client-grants",
        json={
            "client_id": created_client["id"],
            "project_id": project["id"],
        },
        headers=headers,
    )
    assert grant_res.status_code == 201, grant_res.text
    grant = grant_res.json()
    assert grant["client_id"] == created_client["id"]
    assert grant["project_id"] == project["id"]

    # 3. Publish Artifact to Client Portal
    pub_res = await client.post(
        "/api/v1/control-tower/publish",
        json={
            "client_id": created_client["id"],
            "project_id": project["id"],
            "artifact_type": "SHIFT_REPORT",
            "entity_id": opp["id"],
            "title": "Shift Summary Report Week 37",
            "description": "Verified daily drilling progress and meterage achieved.",
        },
        headers=headers,
    )
    assert pub_res.status_code == 201, pub_res.text
    pub = pub_res.json()
    assert pub["artifact_type"] == "SHIFT_REPORT"

    # 4. Fetch Client Portal Overview
    portal_res = await client.get(
        f"/api/v1/control-tower/client-portal/{created_client['id']}/{project['id']}",
        headers=headers,
    )
    assert portal_res.status_code == 200, portal_res.text
    portal = portal_res.json()
    assert portal["client_id"] == created_client["id"]
    assert len(portal["published_artifacts"]) >= 1
