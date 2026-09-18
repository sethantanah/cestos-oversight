import pytest
from datetime import date

from app.tests.test_operational import (
    make_asset,
    make_category,
    make_client,
    make_employee,
    make_project,
    superuser_headers,
)

pytestmark = pytest.mark.integration


async def test_contract_and_rate_card_crud(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Bomi Hills Gold")

    # 1. Create Contract with Rate Cards
    contract_res = await client.post(
        "/api/v1/commercial/contracts",
        json={
            "project_id": project["id"],
            "contract_number": "CNT-2026-001",
            "title": "Bomi Core Drilling Agreement",
            "currency": "USD",
            "start_date": "2026-01-01",
            "rate_cards": [
                {
                    "rate_type": "DRILLING_METER",
                    "drilling_method": "Diamond Core HQ",
                    "depth_from_m": 0.0,
                    "depth_to_m": 50.0,
                    "unit_rate": 40.0,
                    "description": "Shallow HQ Coring",
                },
                {
                    "rate_type": "DRILLING_METER",
                    "drilling_method": "Diamond Core HQ",
                    "depth_from_m": 50.0,
                    "depth_to_m": 150.0,
                    "unit_rate": 50.0,
                    "description": "Medium Depth HQ Coring",
                },
                {
                    "rate_type": "STANDBY_HOURLY",
                    "unit_rate": 100.0,
                    "description": "Rig Standby Rate",
                },
            ],
        },
        headers=headers,
    )
    assert contract_res.status_code == 201, contract_res.text
    contract = contract_res.json()
    assert contract["contract_number"] == "CNT-2026-001"
    assert len(contract["rate_cards"]) == 3

    # 2. Get Contract
    fetched = await client.get(f"/api/v1/commercial/contracts/{contract['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Bomi Core Drilling Agreement"

    # 3. Add Rate Card
    new_card = await client.post(
        f"/api/v1/commercial/contracts/{contract['id']}/rate-cards",
        json={
            "rate_type": "DAYWORK_HOURLY",
            "unit_rate": 150.0,
            "description": "Daywork Rate",
        },
        headers=headers,
    )
    assert new_card.status_code == 201, new_card.text
    assert new_card.json()["unit_rate"] == 150.0


async def test_shift_approval_revenue_auto_posting_and_costing(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    created_client = await make_client(client, headers)
    project = await make_project(client, headers, created_client["id"], name="Dugbe Exploration")

    category = await make_category(client, headers, name="Diamond Rig")
    rig = await make_asset(client, headers, category["id"], name="Rig 101")
    employee = await make_employee(client, headers, first_name="Juah", last_name="Sackie")

    # 1. Create Active Contract with Rate Cards
    contract_res = await client.post(
        "/api/v1/commercial/contracts",
        json={
            "project_id": project["id"],
            "contract_number": "CNT-DUGBE-2026",
            "title": "Dugbe Drilling Contract",
            "currency": "USD",
            "start_date": "2026-01-01",
            "status": "ACTIVE",
            "rate_cards": [
                {
                    "rate_type": "DRILLING_METER",
                    "depth_from_m": 0.0,
                    "depth_to_m": 50.0,
                    "unit_rate": 40.0,
                },
                {
                    "rate_type": "DRILLING_METER",
                    "depth_from_m": 50.0,
                    "depth_to_m": 100.0,
                    "unit_rate": 50.0,
                },
                {
                    "rate_type": "STANDBY_HOURLY",
                    "unit_rate": 100.0,
                },
            ],
        },
        headers=headers,
    )
    assert contract_res.status_code == 201

    # 2. Create Program, Hole & Shift Report
    prog_res = await client.post(
        "/api/v1/drilling/programs",
        json={"project_id": project["id"], "name": "Phase 1"},
        headers=headers,
    )
    assert prog_res.status_code == 201, prog_res.text
    program = prog_res.json()

    hole_res = await client.post(
        "/api/v1/drilling/holes",
        json={"project_id": project["id"], "program_id": program["id"], "hole_number": "DH-101"},
        headers=headers,
    )
    assert hole_res.status_code == 201, hole_res.text
    hole = hole_res.json()

    shift_res = await client.post(
        "/api/v1/drilling/shifts",
        json={
            "project_id": project["id"],
            "rig_id": rig["id"],
            "program_id": program["id"],
            "date": "2026-03-10",
            "shift_type": "DAY",
            "supervisor_id": employee["id"],
            "intervals": [
                {
                    "drill_hole_id": hole["id"],
                    "from_depth_m": 0.0,
                    "to_depth_m": 45.0,
                    "core_recovered_m": 43.5,
                },
                {
                    "drill_hole_id": hole["id"],
                    "from_depth_m": 45.0,
                    "to_depth_m": 90.0,
                    "core_recovered_m": 44.1,
                },
            ],
            "time_segments": [
                {"category": "PRODUCTIVE", "reason_code": "DRILLING", "hours": 9.5},
                {"category": "STANDBY", "reason_code": "WATER_HAULAGE", "hours": 1.5},
            ],
        },
        headers=headers,
    )
    assert shift_res.status_code == 201
    shift = shift_res.json()

    # 3. Submit and Approve Shift Report -> Triggers Revenue Auto-Posting
    await client.post(f"/api/v1/drilling/shifts/{shift['id']}/submit", json={}, headers=headers)
    approved = await client.post(f"/api/v1/drilling/shifts/{shift['id']}/approve", json={}, headers=headers)
    assert approved.status_code == 200

    # 4. Post Operational Costs into Subledger
    # Fuel cost: 200 L @ $5 = $1000
    c1 = await client.post(
        "/api/v1/commercial/cost-entries",
        json={
            "project_id": project["id"],
            "rig_id": rig["id"],
            "shift_report_id": shift["id"],
            "cost_category": "FUEL",
            "description": "Diesel fuel consumed on shift",
            "quantity": 200.0,
            "unit_of_measure": "L",
            "unit_cost": 5.0,
        },
        headers=headers,
    )
    assert c1.status_code == 201

    # Labour cost: 12 hrs @ $50 = $600
    c2 = await client.post(
        "/api/v1/commercial/cost-entries",
        json={
            "project_id": project["id"],
            "rig_id": rig["id"],
            "shift_report_id": shift["id"],
            "cost_category": "LABOUR",
            "description": "Shift crew wages",
            "quantity": 12.0,
            "unit_of_measure": "HRS",
            "unit_cost": 50.0,
        },
        headers=headers,
    )
    assert c2.status_code == 201

    # Parts cost: $400
    c3 = await client.post(
        "/api/v1/commercial/cost-entries",
        json={
            "project_id": project["id"],
            "rig_id": rig["id"],
            "shift_report_id": shift["id"],
            "cost_category": "MAINTENANCE_PARTS",
            "description": "Hydraulic hose replacement",
            "quantity": 1.0,
            "unit_of_measure": "EA",
            "unit_cost": 400.0,
        },
        headers=headers,
    )
    assert c3.status_code == 201

    # 5. Verify Project Financial Summary
    # Revenue:
    #   Interval 1 (0-45m = 45m @ $40) = $1,800
    #   Interval 2 (45-90m = 45m @ $50) = $2,250
    #   Standby (1.5h @ $100) = $150
    #   Total Revenue = $4,200
    # Direct Cost: $1,000 + $600 + $400 = $2,000
    # Net Contribution: $4,200 - $2,000 = $2,200
    # Contribution Margin %: (2200 / 4200) * 100 = 52.38%
    # Cost / Metre: 2000 / 90 = $22.22 / m
    # Litres / Metre: 200 / 90 = 2.22 L / m

    fin_res = await client.get(f"/api/v1/commercial/projects/{project['id']}/financials", headers=headers)
    assert fin_res.status_code == 200, fin_res.text
    fin = fin_res.json()
    assert fin["total_revenue"] == 4150.0
    assert fin["total_direct_cost"] == 2000.0
    assert fin["net_contribution"] == 2150.0
    assert fin["contribution_margin_pct"] == 51.81
    assert fin["total_metres_drilled"] == 90.0
    assert fin["cost_per_metre"] == 22.22
    assert fin["total_fuel_litres"] == 200.0
    assert fin["litres_per_metre"] == 2.22

    # 6. Verify Rig Performance Summary
    rig_res = await client.get(f"/api/v1/commercial/rigs/{rig['id']}/performance", headers=headers)
    assert rig_res.status_code == 200, rig_res.text
    rig_perf = rig_res.json()
    assert rig_perf["total_shifts"] == 1
    assert rig_perf["total_metres_drilled"] == 90.0
    assert rig_perf["total_revenue"] == 4150.0
    assert rig_perf["total_direct_cost"] == 2000.0
    assert rig_perf["net_contribution"] == 2150.0
