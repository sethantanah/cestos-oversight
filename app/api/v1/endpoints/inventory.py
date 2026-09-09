"""Inventory master, document, ledger and analytical endpoints."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.core.exceptions import NotFoundError, ValidationError
from app.db.session import get_session
from app.models import Asset, Employee, Location, Project, User
from app.models import inventory as m
from app.schemas import inventory as schemas
from app.services.inventory import DOCUMENTS, MASTERS, InventoryService
from app.services.inventory_queries import InventoryQueries

router = APIRouter(prefix="/inventory", tags=["inventory"])
operational_router = APIRouter(tags=["inventory"])


def permission(code: str) -> Any:
    async def dependency(
        actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)
    ) -> User:
        InventoryService(session, actor).require(code)
        return actor

    return dependency


def filters(
    search: str | None = None,
    item_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    criticality: str | None = None,
    tracking_method: str | None = None,
    is_consumable: bool | None = None,
    is_active: bool | None = None,
    has_stock: bool | None = None,
    low_stock: bool | None = None,
    out_of_stock: bool | None = None,
    reorder_status: str | None = None,
    status: str | None = None,
    transaction_type: str | None = None,
    transaction_number: str | None = None,
    reference_number: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    days: int = Query(30, ge=1, le=3650),
) -> dict[str, Any]:
    return {key: value for key, value in locals().items() if value is not None}


@router.get("/access")
async def access(
    actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)
) -> Any:
    from app.core.dependencies import scoped_roles

    return {
        "superadmin": actor.is_superuser,
        "permissions": sorted({p.code for r in scoped_roles(actor) for p in r.permissions}),
    }


@router.get("/items")
async def items(
    options: dict[str, Any] = Depends(filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).items(options, page, page_size)


@router.get("/dashboard-summary")
async def dashboard(
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).dashboard()


@router.get("/transactions")
async def transactions(
    options: dict[str, Any] = Depends(filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).transactions(options, page, page_size)


@router.post("/transactions/{identifier}/reverse")
async def reverse(
    identifier: uuid.UUID,
    body: schemas.InventoryReverse,
    actor: User = Depends(permission("inventory.transactions.reverse")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryService(session, actor).reverse(identifier, body.reason)


@router.get("/reconciliation")
async def reconciliation(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.reconciliation.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).reconciliation(page, page_size)


@router.get("/stock")
async def stock(
    item_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
    as_of: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    if as_of and as_of.tzinfo is None:
        raise ValidationError("Historical timestamp must include timezone")
    return await InventoryQueries(session, actor).stock(item_id, store_id, as_of, page, page_size)


@router.get("/lookup")
async def lookup(
    code: str = Query(min_length=1, max_length=255),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    item = await session.scalar(
        select(m.InventoryItem)
        .where(
            m.InventoryItem.organization_id == actor.organization_id,
            or_(
                *(
                    getattr(m.InventoryItem, f) == code
                    for f in ["item_number", "sku", "barcode", "qr_code_value"]
                )
            ),
        )
        .limit(1)
    )
    if not item:
        serial = await session.scalar(
            select(m.InventorySerial)
            .where(
                m.InventorySerial.organization_id == actor.organization_id,
                m.InventorySerial.serial_number == code,
            )
            .limit(1)
        )
        if serial:
            item = await service.ref(m.InventoryItem, serial.item_id)
    if not item:
        raise NotFoundError("Inventory tag not found")
    return await service.overview(item.id)


@router.get("/forecast")
async def forecast(
    options: dict[str, Any] = Depends(filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.forecast.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).items(options, page, page_size)


@router.get("/items/{identifier}/overview")
async def overview(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).overview(identifier)


@router.get("/items/{identifier}/activity")
async def activity(
    identifier: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).activity(identifier, page, page_size)


@router.get("/items/{identifier}/stock")
async def item_stock(
    identifier: uuid.UUID,
    as_of: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryItem, identifier)
    return await service.stock(item_id=identifier, as_of=as_of, page=page, page_size=page_size)


@router.get("/stores/{identifier}/stock")
async def store_stock(
    identifier: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryStore, identifier)
    return await service.stock(store_id=identifier, page=page, page_size=page_size)


@router.get("/stores/{identifier}/dashboard")
async def store_dashboard(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryStore, identifier)
    return await service.dashboard(identifier)


@router.get("/stores/{identifier}/bins")
async def store_bins(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryStore, identifier)
    return await service.listing("bins", {"store_id": identifier})


@router.post("/stores/{identifier}/bins", status_code=201)
async def store_bin_create(
    identifier: uuid.UUID,
    body: schemas.InventoryBinCreate,
    actor: User = Depends(permission("inventory.catalog.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    if body.store_id != identifier:
        raise ValidationError("Store does not match URL")
    return await InventoryService(session, actor).master_save("bins", body)


def master_routes(kind: str, model: Any) -> None:
    code = "inventory.items" if kind == "items" else "inventory.catalog.manage"

    async def listing(
        options: dict[str, Any] = Depends(filters),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        actor: User = Depends(permission("inventory.read")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryQueries(session, actor).listing(kind, options, page, page_size)

    if kind != "items":
        router.add_api_route("/" + kind, listing, methods=["GET"], name=kind + "_list")

    async def create(
        body: Any,
        actor: User = Depends(permission(code + ".create" if kind == "items" else code)),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryService(session, actor).master_save(kind, body)

    create.__annotations__["body"] = getattr(schemas, model.__name__ + "Create")
    router.add_api_route(
        "/" + kind, create, methods=["POST"], status_code=201, name=kind + "_create"
    )

    async def read(
        identifier: uuid.UUID,
        actor: User = Depends(permission("inventory.read")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        service = InventoryService(session, actor)
        return service.public(await service.ref(model, identifier))

    router.add_api_route("/" + kind + "/{identifier}", read, methods=["GET"], name=kind + "_read")

    async def patch(
        identifier: uuid.UUID,
        body: Any,
        actor: User = Depends(permission(code + ".update" if kind == "items" else code)),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryService(session, actor).master_save(kind, body, identifier)

    patch.__annotations__["body"] = getattr(schemas, model.__name__ + "Update")
    router.add_api_route(
        "/" + kind + "/{identifier}", patch, methods=["PATCH"], name=kind + "_update"
    )
    if hasattr(model, "is_active"):

        async def archive(
            identifier: uuid.UUID,
            actor: User = Depends(permission(code + ".archive" if kind == "items" else code)),
            session: AsyncSession = Depends(get_session),
        ) -> Any:
            return await InventoryService(session, actor).archive(kind, identifier)

        router.add_api_route(
            "/" + kind + "/{identifier}/archive", archive, methods=["POST"], name=kind + "_archive"
        )

        async def restore(
            identifier: uuid.UUID,
            actor: User = Depends(permission(code + ".archive" if kind == "items" else code)),
            session: AsyncSession = Depends(get_session),
        ) -> Any:
            return await InventoryService(session, actor).archive(kind, identifier, True)

        router.add_api_route(
            "/" + kind + "/{identifier}/restore", restore, methods=["POST"], name=kind + "_restore"
        )


for kind, model in MASTERS.items():
    master_routes(kind, model)

ACTIONS = {
    "receipts": ["post", "cancel"],
    "issues": ["approve", "post", "cancel"],
    "returns": ["post"],
    "transfers": ["approve", "dispatch", "receive", "cancel"],
    "requests": ["submit", "approve", "reject", "cancel"],
    "adjustments": ["approve", "post", "cancel"],
    "stock-counts": ["start", "submit", "approve", "post"],
}


def document_routes(kind: str) -> None:
    perm = "inventory." + kind.replace("-", "_")

    async def listing(
        options: dict[str, Any] = Depends(filters),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        actor: User = Depends(permission(perm + ".read")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryQueries(session, actor).listing(kind, options, page, page_size)

    router.add_api_route("/" + kind, listing, methods=["GET"], name=kind + "_list")

    async def create(
        body: schemas.InventoryDocumentCreate,
        actor: User = Depends(permission(perm + ".create")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryService(session, actor).document_save(kind, body)

    router.add_api_route(
        "/" + kind, create, methods=["POST"], status_code=201, name=kind + "_create"
    )

    async def read(
        identifier: uuid.UUID,
        actor: User = Depends(permission(perm + ".read")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryService(session, actor).document(kind, identifier)

    router.add_api_route("/" + kind + "/{identifier}", read, methods=["GET"], name=kind + "_read")

    async def patch(
        identifier: uuid.UUID,
        body: schemas.InventoryDocumentCreate,
        actor: User = Depends(permission(perm + ".create")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryService(session, actor).document_save(kind, body, identifier)

    router.add_api_route(
        "/" + kind + "/{identifier}", patch, methods=["PATCH"], name=kind + "_update"
    )
    for action in ACTIONS[kind]:

        def register_action(action: str) -> None:
            grant = (
                "create"
                if action in {"cancel", "start", "submit"}
                else "approve"
                if action == "reject"
                else action
            )

            async def execute(
                identifier: uuid.UUID,
                body: schemas.InventoryAction = schemas.InventoryAction(),
                actor: User = Depends(permission(perm + "." + grant)),
                session: AsyncSession = Depends(get_session),
            ) -> Any:
                return await InventoryService(session, actor).action(kind, identifier, action, body)

            router.add_api_route(
                "/" + kind + "/{identifier}/" + action,
                execute,
                methods=["POST"],
                name=kind + "_" + action,
            )

        register_action(action)


for kind in DOCUMENTS:
    document_routes(kind)


@router.post("/requests/{identifier}/create-issue", status_code=201)
async def request_issue(
    identifier: uuid.UUID,
    body: schemas.InventoryAction,
    actor: User = Depends(permission("inventory.issues.create")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    if not body.store_id:
        raise ValidationError("Choose a store")
    return await InventoryService(session, actor).request_issue(identifier, body.store_id)


@router.post("/reservations", status_code=201)
async def reserve(
    body: schemas.InventoryReservationCreate,
    actor: User = Depends(permission("inventory.reservations.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryService(session, actor).reserve(body)


@router.post("/reservations/{identifier}/release")
async def release(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.reservations.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryService(session, actor).release(identifier)


@router.post("/reservations/{identifier}/cancel")
async def cancel_reservation(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.reservations.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryService(session, actor).release(identifier, True)


def record_routes(kind: str) -> None:
    async def listing(
        options: dict[str, Any] = Depends(filters),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        actor: User = Depends(
            permission(
                "inventory.reservations.read" if kind == "reservations" else "inventory.read"
            )
        ),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryQueries(session, actor).listing(kind, options, page, page_size)

    router.add_api_route("/" + kind, listing, methods=["GET"], name=kind + "_list")


for kind in ["lots", "serials", "custody", "reservations"]:
    record_routes(kind)


@operational_router.get("/assets/{identifier}/inventory-consumption")
async def asset_consumption(
    identifier: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(Asset, identifier)
    return await service.transactions({"asset_id": identifier}, page, page_size)


@operational_router.get("/employees/{identifier}/inventory-issued")
async def employee_issued(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(Employee, identifier)
    return {
        "transactions": await service.transactions({"employee_id": identifier}),
        "custody": await service.listing("custody", {"employee_id": identifier}),
    }


@operational_router.get("/projects/{identifier}/inventory-summary")
async def project_summary(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(Project, identifier)
    stores = list(
        (
            await session.scalars(
                select(m.InventoryStore)
                .join(Location, m.InventoryStore.location_id == Location.id)
                .where(
                    m.InventoryStore.organization_id == actor.organization_id,
                    Location.project_id == identifier,
                )
                .limit(100)
            )
        ).all()
    )
    return {
        "stores": [
            {"store": service.public(store), "dashboard": await service.dashboard(store.id)}
            for store in stores
        ],
        "consumption": await service.transactions(
            {"project_id": identifier, "transaction_type": "ISSUE"}
        ),
    }


def alert_routes(kind: str) -> None:
    async def listing(
        options: dict[str, Any] = Depends(filters),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        actor: User = Depends(permission("inventory.forecast.read")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await InventoryQueries(session, actor).alerts(kind, options, page, page_size)

    router.add_api_route("/" + kind, listing, methods=["GET"], name=kind + "_report")


for report_name in [
    "low-stock",
    "out-of-stock",
    "critical-stock",
    "dead-stock",
    "slow-moving",
    "expiring",
    "aging",
    "issue-suggestions",
]:
    alert_routes(report_name)


@router.get("/consumption")
async def consumption(
    options: dict[str, Any] = Depends(filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).consumption(options, page, page_size)


alert_routes("reorder-recommendations")


@router.post("/imports/{kind}/preview", status_code=201)
async def import_preview(
    kind: str,
    file: UploadFile = File(...),
    actor: User = Depends(permission("inventory.admin")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    from app.services.inventory_imports import InventoryImports

    if not (file.filename or "").lower().endswith(".csv"):
        raise ValidationError("Upload a CSV file; XLSX is a future extension")
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValidationError("CSV file exceeds 2 MB")
    return await InventoryImports(session, actor).preview(
        kind, data, file.filename or "inventory.csv"
    )


@router.post("/imports/{identifier}/confirm")
async def import_confirm(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.admin")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    from app.services.inventory_imports import InventoryImports

    return await InventoryImports(session, actor).confirm(identifier)


@router.get("/reports/{kind}")
async def report(
    kind: str,
    options: dict[str, Any] = Depends(filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    if kind in {"stock", "valuation"}:
        if kind == "valuation":
            service.require("inventory.costs.read")
        return await service.stock(
            options.get("item_id"), options.get("store_id"), page=page, page_size=page_size
        )
    if kind == "transactions":
        return await service.transactions(options, page, page_size)
    if kind == "consumption":
        return await service.consumption(options, page, page_size)
    if kind == "items":
        return await service.items(options, page, page_size)
    if kind in DOCUMENTS:
        service.require("inventory." + kind.replace("-", "_") + ".read")
        return await service.listing(kind, options, page, page_size)
    if kind in {
        "low-stock",
        "out-of-stock",
        "critical-stock",
        "dead-stock",
        "slow-moving",
        "expiring",
        "aging",
        "reorder-recommendations",
    }:
        service.require("inventory.forecast.read")
        return await service.alerts(kind, options, page, page_size)
    raise NotFoundError("Inventory report not found")


@router.get("/exports/{kind}")
async def export(
    kind: str,
    options: dict[str, Any] = Depends(filters),
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    import csv
    import io

    from fastapi.responses import StreamingResponse

    first = await report(kind, options, 1, 200, actor, session)

    async def stream() -> AsyncIterator[str]:
        result = first
        page = 1
        columns = None
        while True:
            rows = result["items"]
            if columns is None:
                columns = list(rows[0]) if rows else ["No records"]
                output = io.StringIO()
                csv.writer(output).writerow(columns)
                yield output.getvalue()
            for row in rows:
                output = io.StringIO()
                values = []
                for key in columns:
                    value = str(row.get(key, "")) if row.get(key) is not None else ""
                    if value.startswith(("=", "+", "-", "@")):
                        value = "'" + value
                    values.append(value)
                csv.writer(output).writerow(values)
                yield output.getvalue()
            if page >= result["pages"]:
                break
            page += 1
            result = await report(kind, options, page, 200, actor, session)

    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="inventory-report.csv"'},
    )
