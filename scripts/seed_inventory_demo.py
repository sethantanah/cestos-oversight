"""Idempotent dummy inventory data. Run after scripts.seed and scripts.seed_demo."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.models import Asset, Employee, Location, Project, Role, User
from app.models import inventory as m
from app.schemas import inventory as s
from app.services.inventory import DOCUMENTS, MASTERS, InventoryService
from scripts.seed import ORGANIZATION_ID


async def seed_inventory(session):
    actor = await session.scalar(
        select(User)
        .where(User.organization_id == ORGANIZATION_ID, User.is_active.is_(True))
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .order_by(User.created_at)
        .limit(1)
    )
    if not actor:
        raise ValueError("Run scripts.seed first")
    service = InventoryService(session, actor)
    locations = list(
        (
            await session.scalars(
                select(Location)
                .where(Location.organization_id == ORGANIZATION_ID)
                .order_by(Location.created_at)
            )
        ).all()
    )
    if not locations:
        raise ValueError("Run scripts.seed_demo first to create locations")

    async def master(kind, name, body):
        model = MASTERS[kind]
        field = "symbol" if kind == "units" else "name"
        row = await session.scalar(
            select(model).where(
                model.organization_id == ORGANIZATION_ID, getattr(model, field) == name
            )
        )
        if row:
            return row
        schema = getattr(s, model.__name__ + "Create")
        result = await service.master_save(kind, schema.model_validate(body))
        return await service.ref(model, result["id"])

    unit = await master("units", "L", {"name": "Litre", "symbol": "L", "precision": 4})
    piece = await master("units", "pcs", {"name": "Piece", "symbol": "pcs", "precision": 0})
    categories = {
        name: await master("categories", name, {"name": name})
        for name in [
            "Drilling Consumables",
            "Mechanical Spares",
            "Hydraulics",
            "Lubricants",
            "Electrical",
            "PPE",
            "Tools",
        ]
    }
    supplier = await master(
        "suppliers",
        "Demo Industrial Supply",
        {"name": "Demo Industrial Supply", "notes": "Fictional inventory demonstration supplier"},
    )
    stores = []
    for index, name in enumerate(
        ["Main Warehouse", "Main Workshop Store", "Project Alpha Store", "Project Bravo Store"]
    ):
        location = next(
            (
                loc
                for loc in locations
                if ("Alpha" in name and "Alpha" in loc.name)
                or ("Bravo" in name and "Bravo" in loc.name)
                or ("Workshop" in name and "Workshop" in loc.name)
            ),
            locations[0],
        )
        stores.append(
            await master(
                "stores",
                name,
                {
                    "name": name,
                    "location_id": location.id,
                    "store_type": "MAIN_WAREHOUSE"
                    if index == 0
                    else "PROJECT_STORE"
                    if index > 1
                    else "WORKSHOP_STORE",
                },
            )
        )
    specs = [
        ("Engine Oil 15W-40", "Lubricants", True),
        ("Hydraulic Oil", "Hydraulics", True),
        ("Grease", "Lubricants", False),
        ("Oil Filter", "Mechanical Spares", False),
        ("Fuel Filter", "Mechanical Spares", False),
        ("Air Filter", "Mechanical Spares", False),
        ("Hydraulic Hose", "Hydraulics", False),
        ("Bearing", "Mechanical Spares", False),
        ("Battery", "Electrical", False),
        ("Drill Bit", "Drilling Consumables", False),
        ("Drill Rod", "Drilling Consumables", False),
        ("Core Tray", "Drilling Consumables", False),
        ("Safety Helmet", "PPE", False),
        ("Safety Gloves", "PPE", False),
        ("Safety Boots", "PPE", False),
        ("Torque Wrench", "Tools", False),
    ]
    items = []
    for index, (name, category, liquid) in enumerate(specs):
        item = await master(
            "items",
            name,
            {
                "name": name,
                "sku": f"DEMO-INV-{index + 1:03}",
                "category_id": categories[category].id,
                "base_unit_id": unit.id if liquid else piece.id,
                "minimum_stock_level": "10",
                "reorder_point": "20",
                "reorder_quantity": "50",
                "safety_stock": "5",
                "lead_time_days": 21,
                "preferred_supplier_id": supplier.id,
                "is_returnable": category == "Tools",
                "criticality": "HIGH"
                if category in {"Mechanical Spares", "Hydraulics"}
                else "MEDIUM",
            },
        )
        items.append(item)
        policy = await session.scalar(
            select(m.InventoryStockPolicy.id).where(
                m.InventoryStockPolicy.item_id == item.id,
                m.InventoryStockPolicy.store_id == stores[0].id,
            )
        )
        if not policy:
            await service.master_save(
                "stock-policies",
                s.InventoryStockPolicyCreate(
                    item_id=item.id,
                    store_id=stores[0].id,
                    minimum_stock_level=10,
                    reorder_point=20,
                    safety_stock=5,
                    lead_time_days=21,
                ),
            )

    async def document(kind, reference, body, actions):
        model = DOCUMENTS[kind][0]
        existing = await session.scalar(
            select(model).where(
                model.organization_id == ORGANIZATION_ID, model.reference_number == reference
            )
        )
        if existing:
            return await service.document(kind, existing.id)
        doc = await service.document_save(
            kind, s.InventoryDocumentCreate.model_validate({**body, "reference_number": reference})
        )
        for action in actions:
            doc = await service.action(kind, doc["id"], action, s.InventoryAction())
        return doc

    await document(
        "receipts",
        "DEMO-INVENTORY-OPENING",
        {
            "store_id": stores[0].id,
            "supplier_id": supplier.id,
            "purpose": "OPENING_BALANCE",
            "items": [
                {
                    "item_id": item.id,
                    "unit_id": item.base_unit_id,
                    "quantity": 1000 if item == items[0] else 100,
                    "unit_cost": "5" if item == items[0] else "12",
                }
                for item in items
            ],
        },
        ["post"],
    )
    oil = items[0]
    await document(
        "transfers",
        "DEMO-INVENTORY-TRANSFER",
        {
            "from_store_id": stores[0].id,
            "to_store_id": stores[2].id,
            "items": [{"item_id": oil.id, "unit_id": oil.base_unit_id, "quantity": 300}],
        },
        ["approve", "dispatch", "receive"],
    )
    project = await session.scalar(
        select(Project).where(
            Project.organization_id == ORGANIZATION_ID, Project.name == "Project Alpha"
        )
    )
    asset = await session.scalar(
        select(Asset).where(Asset.organization_id == ORGANIZATION_ID, Asset.name == "CDR-001")
    )
    employee = await session.scalar(
        select(Employee).where(Employee.organization_id == ORGANIZATION_ID).limit(1)
    )
    issue = await document(
        "issues",
        "DEMO-INVENTORY-ISSUE",
        {
            "store_id": stores[2].id,
            "project_id": project.id if project else None,
            "asset_id": asset.id if asset else None,
            "employee_id": employee.id if employee else None,
            "purpose": "ASSET_CONSUMPTION",
            "items": [{"item_id": oil.id, "unit_id": oil.base_unit_id, "quantity": 100}],
        },
        ["post"],
    )
    await document(
        "returns",
        "DEMO-INVENTORY-RETURN",
        {
            "store_id": stores[2].id,
            "original_issue_id": issue["id"],
            "condition": "GOOD",
            "items": [{"item_id": oil.id, "unit_id": oil.base_unit_id, "quantity": 20}],
        },
        ["post"],
    )
    print(
        "Inventory demo seeded: 16 items, four stores, posted receipt/transfer/issue/return and policies."
    )


async def main():
    engine = build_engine(get_settings())
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await seed_inventory(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=loop_factory)
