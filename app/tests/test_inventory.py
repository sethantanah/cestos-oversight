"""Inventory ledger acceptance, concurrency and traceability regressions."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import selectinload

from app.models import inventory as m
from app.tests.test_asset_domain import (
    make_asset,
    make_category,
    make_client_and_project,
    superuser_headers,
)

pytestmark = pytest.mark.integration


async def create(client, headers, path, body):
    result = await client.post("/api/v1/" + path, headers=headers, json=body)
    assert result.status_code in {200, 201}, result.text
    return result.json()


async def act(client, headers, kind, doc, action, body=None):
    return await create(client, headers, f"inventory/{kind}/{doc['id']}/{action}", body or {})


async def setup(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    unit = await create(
        client, headers, "inventory/units", {"name": "Litre", "symbol": "L", "precision": 4}
    )
    category = await create(
        client, headers, "inventory/categories", {"name": "Lubricants", "is_lubricant": True}
    )
    item = await create(
        client,
        headers,
        "inventory/items",
        {
            "name": "Engine Oil 15W-40",
            "category_id": category["id"],
            "base_unit_id": unit["id"],
            "minimum_stock_level": "100",
            "reorder_point": "150",
            "lead_time_days": 21,
        },
    )
    location = await create(
        client, headers, "locations", {"name": "Warehouse", "location_type": "WAREHOUSE"}
    )
    stores = [
        await create(
            client, headers, "inventory/stores", {"name": name, "location_id": location["id"]}
        )
        for name in ["Main Warehouse", "Project Alpha Store"]
    ]
    return headers, unit, category, item, stores


def line(item, unit, quantity, **kwargs):
    return {"item_id": item["id"], "unit_id": unit["id"], "quantity": str(quantity), **kwargs}


async def balance(client, headers, item, store):
    response = await client.get(
        "/api/v1/inventory/stock",
        headers=headers,
        params={"item_id": item["id"], "store_id": store["id"]},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    return {
        key: sum((Decimal(row[key]) for row in rows), Decimal(0))
        for key in [
            "quantity_on_hand",
            "quantity_available",
            "quantity_reserved",
            "quantity_quarantined",
            "quantity_in_transit",
            "inventory_value",
        ]
    }


async def test_inventory_acceptance_oil_trace(client, identities, session_factory):
    h, u, c, item, stores = await setup(client, identities, session_factory)
    main, alpha = stores
    receipt = await create(
        client,
        h,
        "inventory/receipts",
        {"store_id": main["id"], "items": [line(item, u, 1000, unit_cost="5")]},
    )
    assert (await balance(client, h, item, main))["quantity_on_hand"] == 0
    await act(client, h, "receipts", receipt, "post")
    await act(client, h, "receipts", receipt, "post")
    assert (await balance(client, h, item, main))["quantity_on_hand"] == 1000
    before = datetime.now(UTC).isoformat()
    transfer = await create(
        client,
        h,
        "inventory/transfers",
        {"from_store_id": main["id"], "to_store_id": alpha["id"], "items": [line(item, u, 300)]},
    )
    await act(client, h, "transfers", transfer, "approve")
    await act(client, h, "transfers", transfer, "dispatch")
    assert (await balance(client, h, item, main))["quantity_in_transit"] == 300
    assert (await balance(client, h, item, alpha))["quantity_available"] == 0
    await act(client, h, "transfers", transfer, "receive")
    await act(client, h, "transfers", transfer, "receive")
    assert (await balance(client, h, item, main))["quantity_on_hand"] == 700
    reservation = await create(
        client,
        h,
        "inventory/reservations",
        {"item_id": item["id"], "store_id": alpha["id"], "quantity": "50"},
    )
    assert (await balance(client, h, item, alpha))["quantity_available"] == 250
    _, project = await make_client_and_project(client, h)
    ac = await make_category(client, h)
    asset = await make_asset(client, h, ac["id"])
    employee = await create(
        client, h, "employees", {"first_name": "Store", "last_name": "Mechanic"}
    )
    issue = await create(
        client,
        h,
        "inventory/issues",
        {
            "store_id": alpha["id"],
            "project_id": project["id"],
            "asset_id": asset["id"],
            "employee_id": employee["id"],
            "purpose": "ASSET_CONSUMPTION",
            "items": [line(item, u, 100)],
        },
    )
    await act(client, h, "issues", issue, "post")
    assert (await balance(client, h, item, alpha))["quantity_available"] == 150
    too_big = await create(
        client, h, "inventory/issues", {"store_id": alpha["id"], "items": [line(item, u, 200)]}
    )
    assert (
        await client.post(f"/api/v1/inventory/issues/{too_big['id']}/post", headers=h, json={})
    ).status_code == 409
    for quantity, condition in [(20, "GOOD"), (10, "DAMAGED")]:
        returned = await create(
            client,
            h,
            "inventory/returns",
            {
                "store_id": alpha["id"],
                "original_issue_id": issue["id"],
                "condition": condition,
                "items": [line(item, u, quantity)],
            },
        )
        await act(client, h, "returns", returned, "post")
    stock = await balance(client, h, item, alpha)
    assert (
        stock["quantity_on_hand"] == 230
        and stock["quantity_quarantined"] == 10
        and stock["quantity_available"] == 170
    )
    count = await create(
        client,
        h,
        "inventory/stock-counts",
        {"store_id": alpha["id"], "items": [line(item, u, 1, counted_quantity="225")]},
    )
    await act(client, h, "stock-counts", count, "start")
    await act(client, h, "stock-counts", count, "submit")
    await act(client, h, "stock-counts", count, "approve")
    await act(client, h, "stock-counts", count, "post")
    assert (await balance(client, h, item, alpha))["quantity_on_hand"] == 225
    assert (await balance(client, h, item, alpha))["inventory_value"] == 1125
    history = (
        await client.get(
            "/api/v1/inventory/stock",
            headers=h,
            params={"item_id": item["id"], "store_id": main["id"], "as_of": before},
        )
    ).json()
    assert Decimal(history["items"][0]["quantity_on_hand"]) == 1000
    check = (await client.get("/api/v1/inventory/reconciliation", headers=h)).json()
    assert check["consistent"], check
    overview = (
        await client.get(f"/api/v1/inventory/items/{item['id']}/overview", headers=h)
    ).json()
    assert (
        Decimal(overview["consumption"]) == 70
        and Decimal(overview["average_daily_consumption"]) > 0
    )
    for url in [
        f"projects/{project['id']}/inventory-summary",
        f"assets/{asset['id']}/inventory-consumption",
        f"employees/{employee['id']}/inventory-issued",
        "inventory/dashboard-summary",
        "inventory/forecast",
    ]:
        response = await client.get("/api/v1/" + url, headers=h)
        assert response.status_code == 200, response.text
    await act(client, h, "reservations", reservation, "release")
    assert (await balance(client, h, item, alpha))["quantity_reserved"] == 0


async def test_inventory_concurrent_issue_and_weighted_average(client, identities, session_factory):
    h, u, c, item, stores = await setup(client, identities, session_factory)
    store = stores[0]
    for quantity, cost in [(5, 2), (5, 4)]:
        doc = await create(
            client,
            h,
            "inventory/receipts",
            {"store_id": store["id"], "items": [line(item, u, quantity, unit_cost=str(cost))]},
        )
        await act(client, h, "receipts", doc, "post")
    assert (await balance(client, h, item, store))["inventory_value"] == 30
    docs = [
        await create(
            client, h, "inventory/issues", {"store_id": store["id"], "items": [line(item, u, q)]}
        )
        for q in [8, 5]
    ]
    responses = await asyncio.gather(
        *(
            client.post(f"/api/v1/inventory/issues/{doc['id']}/post", headers=h, json={})
            for doc in docs
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert (await client.get("/api/v1/inventory/reconciliation", headers=h)).json()["consistent"]


async def test_inventory_permissions_isolation_and_cost_redaction(
    client, identities, session_factory
):
    from app.models import Permission, Role, User
    from app.tests.conftest import login

    h, u, c, item, stores = await setup(client, identities, session_factory)
    async with session_factory() as session:
        user = await session.get(User, identities["denied"].id, options=[selectinload(User.roles)])
        read = Permission(code="inventory.read")
        session.add(read)
        user.roles = [
            Role(name="Stock reader", organization_id=user.organization_id, permissions=[read])
        ]
        await session.commit()
    own = {"Authorization": "Bearer " + (await login(client, identities["denied"]))["access_token"]}
    assert (
        await client.post(
            "/api/v1/inventory/items",
            headers=own,
            json={"name": "Denied", "category_id": c["id"], "base_unit_id": u["id"]},
        )
    ).status_code == 403
    doc = await create(
        client,
        h,
        "inventory/receipts",
        {"store_id": stores[0]["id"], "items": [line(item, u, 10, unit_cost="9876")]},
    )
    await act(client, h, "receipts", doc, "post")
    for url in [
        "inventory/items",
        "inventory/transactions",
        "inventory/stock",
        "inventory/dashboard-summary",
        f"inventory/items/{item['id']}/overview",
        "inventory/exports/stock",
    ]:
        response = await client.get("/api/v1/" + url, headers=own)
        assert response.status_code == 200, response.text
        assert (
            "9876" not in response.text
            and "unit_cost" not in response.text
            and "inventory_value" not in response.text
        )
    other = await superuser_headers(client, identities["other"], session_factory)
    assert (
        await client.get("/api/v1/inventory/items/" + item["id"], headers=other)
    ).status_code == 404
    invalid = await client.post(
        "/api/v1/inventory/items",
        headers=other,
        json={"name": "Cross org", "category_id": c["id"], "base_unit_id": u["id"]},
    )
    assert invalid.status_code == 404


async def test_inventory_conversion_approvals_requests_and_reversal(
    client, identities, session_factory
):
    h, u, c, item, stores = await setup(client, identities, session_factory)
    store = stores[0]
    drum = await create(
        client, h, "inventory/units", {"name": "Drum", "symbol": "drum", "precision": 0}
    )
    await create(
        client,
        h,
        "inventory/conversions",
        {
            "item_id": item["id"],
            "from_unit_id": drum["id"],
            "to_unit_id": u["id"],
            "conversion_factor": "200",
        },
    )
    doc = await create(
        client,
        h,
        "inventory/receipts",
        {"store_id": store["id"], "items": [line(item, drum, 2, unit_cost="1000")]},
    )
    await act(client, h, "receipts", doc, "post")
    assert (await balance(client, h, item, store))["quantity_on_hand"] == 400
    req = await create(client, h, "inventory/requests", {"items": [line(item, u, 20)]})
    await act(client, h, "requests", req, "submit")
    await act(client, h, "requests", req, "approve")
    issued = await act(client, h, "requests", req, "create-issue", {"store_id": store["id"]})
    assert (await act(client, h, "requests", req, "create-issue", {"store_id": store["id"]}))[
        "id"
    ] == issued["id"]
    await act(client, h, "issues", issued, "post")
    assert (await client.get("/api/v1/inventory/requests/" + req["id"], headers=h)).json()[
        "status"
    ] == "FULFILLED"
    plain = await create(
        client, h, "inventory/issues", {"store_id": store["id"], "items": [line(item, u, 10)]}
    )
    await act(client, h, "issues", plain, "post")
    tx = (
        await client.get(
            "/api/v1/inventory/transactions", headers=h, params={"transaction_type": "ISSUE"}
        )
    ).json()["items"][0]
    await create(
        client,
        h,
        "inventory/transactions/" + tx["id"] + "/reverse",
        {"reason": "Wrong quantity entered"},
    )
    await create(client, h, "inventory/transactions/" + tx["id"] + "/reverse", {"reason": "Retry"})
    assert (await balance(client, h, item, store))["quantity_on_hand"] == 380
    assert (await client.get("/api/v1/inventory/reconciliation", headers=h)).json()["consistent"]
    draft = await create(
        client,
        h,
        "inventory/adjustments",
        {
            "store_id": store["id"],
            "purpose": "NEGATIVE_ADJUSTMENT",
            "reason": "Loss confirmed",
            "items": [line(item, u, 3)],
        },
    )
    assert (
        await client.post(f"/api/v1/inventory/adjustments/{draft['id']}/post", headers=h, json={})
    ).status_code == 409
    await act(client, h, "adjustments", draft, "approve")
    await act(client, h, "adjustments", draft, "post")
    assert (await balance(client, h, item, store))["quantity_on_hand"] == 377


async def test_inventory_batch_serial_quarantine_and_custody(client, identities, session_factory):
    h, u, c, item, stores = await setup(client, identities, session_factory)
    store = stores[0]
    tool = await create(
        client,
        h,
        "inventory/items",
        {
            "name": "Calibrated tool",
            "category_id": c["id"],
            "base_unit_id": u["id"],
            "tracking_method": "SERIALIZED",
            "requires_batch_tracking": True,
            "requires_expiry_tracking": True,
            "is_returnable": True,
        },
    )
    expiry = (datetime.now(UTC) + timedelta(days=100)).date().isoformat()
    receipt = await create(
        client,
        h,
        "inventory/receipts",
        {
            "store_id": store["id"],
            "items": [
                line(
                    tool,
                    u,
                    1,
                    unit_cost="500",
                    serial_number="TOOL-1",
                    lot_number="B1",
                    expiry_date=expiry,
                )
            ],
        },
    )
    posted = await act(client, h, "receipts", receipt, "post")
    detail = posted["items"][0]
    serial, lot = detail["serial_id"], detail["lot_id"]
    reservation = await create(
        client,
        h,
        "inventory/reservations",
        {
            "item_id": tool["id"],
            "store_id": store["id"],
            "quantity": "1",
            "serial_id": serial,
            "lot_id": lot,
        },
    )
    issue = await create(
        client,
        h,
        "inventory/issues",
        {
            "store_id": store["id"],
            "reservation_id": reservation["id"],
            "items": [line(tool, u, 1, serial_id=serial, lot_id=lot)],
        },
    )
    await act(client, h, "issues", issue, "post")
    duplicate = await create(
        client,
        h,
        "inventory/issues",
        {"store_id": store["id"], "items": [line(tool, u, 1, serial_id=serial, lot_id=lot)]},
    )
    assert (
        await client.post(f"/api/v1/inventory/issues/{duplicate['id']}/post", headers=h, json={})
    ).status_code == 409
    returned = await create(
        client,
        h,
        "inventory/returns",
        {
            "store_id": store["id"],
            "original_issue_id": issue["id"],
            "condition": "DAMAGED",
            "items": [line(tool, u, 1, serial_id=serial, lot_id=lot)],
        },
    )
    await act(client, h, "returns", returned, "post")
    assert (await balance(client, h, tool, store))["quantity_available"] == 0
    custody = (await client.get("/api/v1/inventory/custody", headers=h)).json()["items"]
    assert custody[0]["status"] == "RETURNED"
    async with session_factory() as session:
        batch = await session.get(m.InventoryLot, uuid.UUID(lot))
        batch.expiry_date = datetime.now(UTC).date() - timedelta(days=1)
        await session.commit()
    release = await create(
        client,
        h,
        "inventory/adjustments",
        {
            "store_id": store["id"],
            "purpose": "RELEASE_FROM_QUARANTINE",
            "reason": "Checked tool",
            "items": [line(tool, u, 1, serial_id=serial, lot_id=lot)],
        },
    )
    await act(client, h, "adjustments", release, "approve")
    assert (
        await client.post(f"/api/v1/inventory/adjustments/{release['id']}/post", headers=h, json={})
    ).status_code == 409


async def test_inventory_csv_preview_atomicity_and_reports(client, identities, session_factory):
    h, u, c, item, stores = await setup(client, identities, session_factory)
    store = stores[0]
    csv = (
        f"store_id,item_id,unit_id,quantity,unit_cost\n{store['id']},{item['id']},{u['id']},50,2\n"
    )
    preview = await client.post(
        "/api/v1/inventory/imports/opening-stock/preview",
        headers=h,
        files={"file": ("stock.csv", csv, "text/csv")},
    )
    assert preview.status_code == 201, preview.text
    data = preview.json()
    assert data["can_import"], data
    assert (await balance(client, h, item, store))["quantity_on_hand"] == 0
    await create(client, h, "inventory/imports/" + data["id"] + "/confirm", {})
    await create(client, h, "inventory/imports/" + data["id"] + "/confirm", {})
    assert (await balance(client, h, item, store))["quantity_on_hand"] == 50
    invalid = csv + f"{store['id']},{item['id']},{u['id']},-1,2\n"
    preview = await client.post(
        "/api/v1/inventory/imports/opening-stock/preview",
        headers=h,
        files={"file": ("bad.csv", invalid, "text/csv")},
    )
    assert not preview.json()["can_import"], preview.text
    assert (await balance(client, h, item, store))["quantity_on_hand"] == 50
    for report in [
        "low-stock",
        "out-of-stock",
        "critical-stock",
        "dead-stock",
        "slow-moving",
        "expiring",
        "aging",
        "reorder-recommendations",
        "consumption",
        "issue-suggestions",
    ]:
        response = await client.get("/api/v1/inventory/" + report, headers=h)
        assert response.status_code == 200, response.text
    response = await client.get("/api/v1/inventory/exports/stock", headers=h)
    assert response.status_code == 200 and "quantity_on_hand" in response.text
