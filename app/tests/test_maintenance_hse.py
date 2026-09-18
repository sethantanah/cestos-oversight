import pytest

from app.tests.test_operational import (
    make_asset,
    make_category,
    make_client,
    make_employee,
    make_project,
    superuser_headers,
)

pytestmark = pytest.mark.integration


async def test_maintenance_work_order_lifecycle_and_reliability(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Zodiac Project")

    category = await make_category(client, headers, name="RC Rig")
    rig = await make_asset(client, headers, category["id"], name="RC Rig 202")
    technician = await make_employee(client, headers, first_name="Kofi", last_name="Mensah", job_title="Mechanic")

    # 1. Create Maintenance Work Order with embedded Cost Line
    wo_res = await client.post(
        "/api/v1/maintenance/work-orders",
        json={
            "asset_id": rig["id"],
            "project_id": project["id"],
            "title": "Main Hydraulic Pump Replacement",
            "description": "Pressure drop observed during deep drilling.",
            "work_type": "CORRECTIVE",
            "priority": "HIGH",
            "failure_taxonomy": "HYDRAULIC",
            "assigned_technician_id": technician["id"],
            "cost_lines": [
                {
                    "cost_type": "PARTS",
                    "description": "Hydraulic Main Pump Assembly",
                    "part_number": "HYD-PMP-990",
                    "quantity": 1.0,
                    "unit_cost": 1200.0,
                },
                {
                    "cost_type": "LABOUR",
                    "description": "Technician Repair Labour",
                    "quantity": 4.0,
                    "unit_cost": 75.0,
                },
            ],
        },
        headers=headers,
    )
    assert wo_res.status_code == 201, wo_res.text
    wo = wo_res.json()
    assert wo["wo_number"].startswith("MWO-")
    assert wo["status"] == "OPEN"
    assert len(wo["cost_lines"]) == 2

    # 2. Add an additional cost line
    cl_res = await client.post(
        f"/api/v1/maintenance/work-orders/{wo['id']}/cost-lines",
        json={
            "cost_type": "PARTS",
            "description": "Inline Hydraulic Hose Filter",
            "part_number": "FLT-772",
            "quantity": 2.0,
            "unit_cost": 50.0,
        },
        headers=headers,
    )
    assert cl_res.status_code == 201, cl_res.text

    # 3. Complete Work Order
    comp_res = await client.post(
        f"/api/v1/maintenance/work-orders/{wo['id']}/complete",
        json={
            "root_cause": "Worn impeller seal caused pressure degradation.",
            "remedy": "Replaced hydraulic pump assembly and inline filter.",
            "downtime_hours": 6.0,
            "estimated_lost_contribution": 300.0,
            "notes": "Rig re-commissioned and tested at full pressure.",
        },
        headers=headers,
    )
    assert comp_res.status_code == 200, comp_res.text
    completed_wo = comp_res.json()
    assert completed_wo["status"] == "COMPLETED"
    assert completed_wo["downtime_hours"] == 6.0

    # 4. Verify Asset Reliability Summary
    rel_res = await client.get(f"/api/v1/maintenance/assets/{rig['id']}/reliability", headers=headers)
    assert rel_res.status_code == 200, rel_res.text
    rel = rel_res.json()
    assert rel["total_work_orders"] == 1
    assert rel["completed_work_orders"] == 1
    assert rel["open_work_orders"] == 0
    assert rel["total_downtime_hours"] == 6.0
    assert rel["total_maintenance_cost"] == 1600.0  # 1200 + 300 + 100
    assert rel["failure_count_by_taxonomy"]["HYDRAULIC"] == 1

    # Verify Auto-Posted Subledger Costs in Project Financials
    fin_res = await client.get(f"/api/v1/commercial/projects/{project['id']}/financials", headers=headers)
    assert fin_res.status_code == 200
    fin = fin_res.json()
    assert fin["total_direct_cost"] == 1600.0
    assert fin["cost_breakdown_by_category"]["MAINTENANCE_PARTS"] == 1300.0
    assert fin["cost_breakdown_by_category"]["LABOUR"] == 300.0


async def test_hse_incident_and_corrective_action_lifecycle(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Bomi West Site")
    employee = await make_employee(client, headers, first_name="Tarnue", last_name="Flomo", job_title="Safety Officer")

    # 1. Create HSE Incident with embedded Corrective Action
    inc_res = await client.post(
        "/api/v1/hse/incidents",
        json={
            "title": "Minor Hydraulic Hose Leak Near Rig 202",
            "incident_type": "ENVIRONMENTAL_SPILL",
            "severity": "MEDIUM",
            "occurred_at": "2026-03-12T14:30:00Z",
            "project_id": project["id"],
            "reported_by_id": employee["id"],
            "description": "Approximately 5 litres of hydraulic oil leaked onto containment tray.",
            "immediate_actions_taken": "Applied oil absorbent pads and shut down rig feed line.",
            "actions": [
                {
                    "description": "Clean and safely dispose of contaminated absorbent materials.",
                    "assigned_to_id": employee["id"],
                    "due_date": "2026-03-15",
                }
            ],
        },
        headers=headers,
    )
    assert inc_res.status_code == 201, inc_res.text
    incident = inc_res.json()
    assert incident["incident_number"].startswith("HSE-")
    assert incident["status"] == "REPORTED"
    assert len(incident["actions"]) == 1
    action1 = incident["actions"][0]
    assert action1["action_number"].startswith("CAP-")
    assert action1["status"] == "OPEN"

    # 2. Add an additional Action to Incident
    act2_res = await client.post(
        f"/api/v1/hse/incidents/{incident['id']}/actions",
        json={
            "description": "Inspect all high-pressure hose fittings across active rigs.",
            "assigned_to_id": employee["id"],
            "due_date": "2026-03-20",
        },
        headers=headers,
    )
    assert act2_res.status_code == 201, act2_res.text

    # 3. Close Corrective Action
    close_act = await client.patch(
        f"/api/v1/hse/actions/{action1['id']}",
        json={
            "status": "CLOSED",
            "closure_notes": "Spill contained and contaminated pads disposed at certified facility.",
        },
        headers=headers,
    )
    assert close_act.status_code == 200, close_act.text
    closed_action = close_act.json()
    assert closed_action["status"] == "CLOSED"
    assert closed_action["closed_at"] is not None

    # 4. Update Incident Status
    up_inc = await client.patch(
        f"/api/v1/hse/incidents/{incident['id']}",
        json={
            "status": "CLOSED",
            "root_cause_analysis": "Fitting failure due to vibration fatigue.",
        },
        headers=headers,
    )
    assert up_inc.status_code == 200, up_inc.text
    updated_incident = up_inc.json()
    assert updated_incident["status"] == "CLOSED"
    assert updated_incident["root_cause_analysis"] == "Fitting failure due to vibration fatigue."
