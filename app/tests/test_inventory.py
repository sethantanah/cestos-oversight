"""Inventory ledger acceptance, concurrency and traceability regressions."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

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
