"""Inventory master, document, ledger and analytical endpoints."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user, request_storage
from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import LocalStorage
from app.db.session import get_session
from app.models import Asset, Employee, Location, Project, User
from app.models import inventory as m
from app.models.operational_logs import AssetLogFile
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


@router.get("/stats")
async def get_inventory_stats(
    store_id: uuid.UUID | None = Query(None),
    category_id: uuid.UUID | None = Query(None),
    supplier_id: uuid.UUID | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    from datetime import UTC, datetime, timedelta
    from sqlalchemy import func, select
    from app.models import Project
    from app.models.inventory import (
        InventoryBalance,
        InventoryCategory,
        InventoryIssue,
        InventoryIssueItem,
        InventoryItem,
        InventoryStockPolicy,
    )

    # 1. Consumption by Project (Last 30 days — total value issued)
    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)

    issue_stmt = (
        select(
            func.coalesce(Project.name, "General Operations").label("project"),
            func.coalesce(
                func.sum(InventoryIssueItem.total_cost),
                func.sum(InventoryIssueItem.quantity * func.coalesce(InventoryIssueItem.unit_cost, 0)),
                0,
            ).label("value"),
        )
        .join(InventoryIssue, InventoryIssueItem.document_id == InventoryIssue.id)
        .outerjoin(Project, InventoryIssue.project_id == Project.id)
        .where(
            InventoryIssue.organization_id == actor.organization_id,
            InventoryIssue.transaction_date >= thirty_days_ago,
        )
    )
    if store_id:
        issue_stmt = issue_stmt.where(InventoryIssue.store_id == store_id)
    if project_id:
        issue_stmt = issue_stmt.where(InventoryIssue.project_id == project_id)

    issue_stmt = issue_stmt.group_by(Project.name, Project.id).order_by(
        func.coalesce(
            func.sum(InventoryIssueItem.total_cost),
            func.sum(InventoryIssueItem.quantity * func.coalesce(InventoryIssueItem.unit_cost, 0)),
            0,
        ).desc()
    )
    issue_rows = (await session.execute(issue_stmt)).all()
    consumption_by_project = [
        {"project": str(r.project), "value": float(r.value or 0)} for r in issue_rows
    ]

    # Fallback to project inventory policies if no issue transactions exist yet
    if not consumption_by_project:
        proj_stock_stmt = (
            select(
                Project.name.label("project"),
                func.coalesce(
                    func.sum(
                        InventoryItem.standard_unit_cost
                        * func.coalesce(InventoryStockPolicy.minimum_stock_level, 1)
                    ),
                    0,
                ).label("value"),
            )
            .select_from(Project)
            .where(Project.organization_id == actor.organization_id, Project.archived_at.is_(None))
        )
        if project_id:
            proj_stock_stmt = proj_stock_stmt.where(Project.id == project_id)
        proj_stock_stmt = proj_stock_stmt.group_by(Project.name, Project.id).limit(5)
        p_rows = (await session.execute(proj_stock_stmt)).all()
        consumption_by_project = [
            {"project": str(r.project), "value": float(r.value or 0)} for r in p_rows
        ]

    # 2. Inventory Value by Category (Current stock valuation breakdown)
    cat_stmt = (
        select(
            InventoryCategory.name.label("name"),
            func.coalesce(func.sum(InventoryBalance.inventory_value), 0).label("value"),
        )
        .join(InventoryItem, InventoryBalance.item_id == InventoryItem.id)
        .join(InventoryCategory, InventoryItem.category_id == InventoryCategory.id)
        .where(
            InventoryCategory.organization_id == actor.organization_id,
            InventoryCategory.archived_at.is_(None),
            InventoryItem.archived_at.is_(None),
        )
    )
    if category_id:
        cat_stmt = cat_stmt.where(InventoryCategory.id == category_id)
    if supplier_id:
        cat_stmt = cat_stmt.where(InventoryItem.preferred_supplier_id == supplier_id)
    if store_id:
        cat_stmt = cat_stmt.where(InventoryBalance.store_id == store_id)

    cat_stmt = cat_stmt.group_by(InventoryCategory.name, InventoryCategory.id).order_by(
        func.coalesce(func.sum(InventoryBalance.inventory_value), 0).desc()
    )
    cat_rows = (await session.execute(cat_stmt)).all()
    value_by_category = [
        {"name": str(r.name), "value": float(r.value or 0)}
        for r in cat_rows
        if r.value and float(r.value) > 0
    ]

    # Fallback to stock policy standard cost calculation if balances yield empty list
    if not value_by_category:
        fallback_cat_stmt = (
            select(
                InventoryCategory.name.label("name"),
                func.coalesce(
                    func.sum(
                        InventoryItem.standard_unit_cost
                        * func.coalesce(InventoryStockPolicy.minimum_stock_level, 1)
                    ),
                    0,
                ).label("value"),
            )
            .join(InventoryItem, InventoryItem.category_id == InventoryCategory.id)
            .outerjoin(InventoryStockPolicy, InventoryStockPolicy.item_id == InventoryItem.id)
            .where(
                InventoryCategory.organization_id == actor.organization_id,
                InventoryCategory.archived_at.is_(None),
                InventoryItem.archived_at.is_(None),
            )
        )
        if category_id:
            fallback_cat_stmt = fallback_cat_stmt.where(InventoryCategory.id == category_id)
        if supplier_id:
            fallback_cat_stmt = fallback_cat_stmt.where(InventoryItem.preferred_supplier_id == supplier_id)
        if store_id:
            fallback_cat_stmt = fallback_cat_stmt.where(InventoryStockPolicy.store_id == store_id)
        fallback_cat_stmt = fallback_cat_stmt.group_by(InventoryCategory.name, InventoryCategory.id).order_by(
            func.coalesce(
                func.sum(
                    InventoryItem.standard_unit_cost
                    * func.coalesce(InventoryStockPolicy.minimum_stock_level, 1)
                ),
                0,
            ).desc()
        )
        cat_rows = (await session.execute(fallback_cat_stmt)).all()
        value_by_category = [
            {"name": str(r.name), "value": float(r.value or 0)}
            for r in cat_rows
            if r.value and float(r.value) > 0
        ]

    # 3. Consumption Trend over time
    trend_stmt = (
        select(
            func.date(InventoryIssue.transaction_date).label("date"),
            func.coalesce(Project.name, "General Operations").label("project"),
            func.coalesce(
                func.sum(InventoryIssueItem.total_cost),
                func.sum(InventoryIssueItem.quantity * func.coalesce(InventoryIssueItem.unit_cost, 0)),
                0,
            ).label("amount"),
        )
        .join(InventoryIssue, InventoryIssueItem.document_id == InventoryIssue.id)
        .outerjoin(Project, InventoryIssue.project_id == Project.id)
        .where(
            InventoryIssue.organization_id == actor.organization_id,
            InventoryIssue.transaction_date >= thirty_days_ago,
        )
    )
    if store_id:
        trend_stmt = trend_stmt.where(InventoryIssue.store_id == store_id)
    if project_id:
        trend_stmt = trend_stmt.where(InventoryIssue.project_id == project_id)

    trend_stmt = trend_stmt.group_by(
        func.date(InventoryIssue.transaction_date),
        Project.name,
        Project.id,
    ).order_by(func.date(InventoryIssue.transaction_date).asc())

    trend_rows = (await session.execute(trend_stmt)).all()
    trend_map: dict[str, dict[str, Any]] = {}
    for r in trend_rows:
        d_str = r.date.strftime("%b %d") if hasattr(r.date, "strftime") else str(r.date)
        if d_str not in trend_map:
            trend_map[d_str] = {"date": d_str}
        trend_map[d_str][str(r.project)] = float(r.amount or 0)

    consumption_trend = list(trend_map.values())

    return {
        "consumption_by_project": consumption_by_project,
        "value_by_category": value_by_category,
        "consumption_trend": consumption_trend,
    }


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


# ---- Store & Item Attachments / Media ----


@router.get("/stores/{identifier}/files")
async def store_files(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryStore, identifier)
    rows = (
        await session.scalars(
            select(AssetLogFile)
            .where(
                AssetLogFile.organization_id == actor.organization_id,
                AssetLogFile.log_type == "STORE",
                AssetLogFile.log_id == identifier,
            )
            .order_by(AssetLogFile.created_at.desc())
        )
    ).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "file_name": r.file_name,
            "mime_type": r.mime_type,
            "size_bytes": r.size_bytes,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/stores/{identifier}/files", status_code=201)
async def store_file_upload(
    identifier: uuid.UUID,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    actor: User = Depends(permission("inventory.catalog.manage")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryStore, identifier)
    data = await file.read(storage.max_bytes + 1)
    stored = storage.save("stores", data, file.filename, file.content_type)
    row = AssetLogFile(
        organization_id=actor.organization_id,
        asset_id=identifier,
        log_type="STORE",
        log_id=identifier,
        title=title or file.filename,
        storage_path=stored.relative_path,
        file_name=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        created_by_id=actor.id,
        updated_by_id=actor.id,
    )
    session.add(row)
    await session.commit()
    return {
        "id": row.id,
        "title": row.title,
        "file_name": row.file_name,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
    }


@router.get("/store-files/{file_id}/download")
async def download_store_file(
    file_id: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> FileResponse:
    row = (
        await session.scalars(
            select(AssetLogFile).where(
                AssetLogFile.id == file_id,
                AssetLogFile.organization_id == actor.organization_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("File not found")
    path = storage.resolve(row.storage_path)
    return FileResponse(
        path, media_type=row.mime_type or "application/octet-stream", filename=row.file_name
    )


@router.get("/items/{identifier}/files")
async def item_files(
    identifier: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryItem, identifier)
    rows = (
        await session.scalars(
            select(AssetLogFile)
            .where(
                AssetLogFile.organization_id == actor.organization_id,
                AssetLogFile.log_type == "ITEM",
                AssetLogFile.log_id == identifier,
            )
            .order_by(AssetLogFile.created_at.desc())
        )
    ).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "file_name": r.file_name,
            "mime_type": r.mime_type,
            "size_bytes": r.size_bytes,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/items/{identifier}/files", status_code=201)
async def item_file_upload(
    identifier: uuid.UUID,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    actor: User = Depends(permission("inventory.catalog.manage")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> Any:
    service = InventoryQueries(session, actor)
    await service.ref(m.InventoryItem, identifier)
    data = await file.read(storage.max_bytes + 1)
    stored = storage.save("items", data, file.filename, file.content_type)
    row = AssetLogFile(
        organization_id=actor.organization_id,
        asset_id=identifier,
        log_type="ITEM",
        log_id=identifier,
        title=title or file.filename,
        storage_path=stored.relative_path,
        file_name=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        created_by_id=actor.id,
        updated_by_id=actor.id,
    )
    session.add(row)
    await session.commit()
    return {
        "id": row.id,
        "title": row.title,
        "file_name": row.file_name,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
    }


@router.post("/items/{identifier}/photo", status_code=200)
async def item_photo_upload(
    identifier: uuid.UUID,
    file: UploadFile = File(...),
    actor: User = Depends(permission("inventory.catalog.manage")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> Any:
    service = InventoryQueries(session, actor)
    item = await service.ref(m.InventoryItem, identifier, True)
    data = await file.read(storage.max_bytes + 1)
    stored = storage.save("item-photos", data, file.filename, file.content_type)
    row = AssetLogFile(
        organization_id=actor.organization_id,
        asset_id=identifier,
        log_type="ITEM_PHOTO",
        log_id=identifier,
        title=file.filename,
        storage_path=stored.relative_path,
        file_name=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        created_by_id=actor.id,
        updated_by_id=actor.id,
    )
    session.add(row)
    await session.flush()
    item.image_url = f"/api/v1/inventory/item-files/{row.id}/download"
    await session.commit()
    return {"image_url": item.image_url}


@router.get("/item-files/{file_id}/download")
async def download_item_file(
    file_id: uuid.UUID,
    actor: User = Depends(permission("inventory.read")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> FileResponse:
    row = (
        await session.scalars(
            select(AssetLogFile).where(
                AssetLogFile.id == file_id,
                AssetLogFile.organization_id == actor.organization_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("File not found")
    path = storage.resolve(row.storage_path)
    return FileResponse(
        path, media_type=row.mime_type or "application/octet-stream", filename=row.file_name
    )


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
    "stock-counts": ["start", "restart", "submit", "approve", "post"],
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
                if action in {"cancel", "start", "restart", "submit"}
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
    storage: LocalStorage = Depends(request_storage),
) -> Any:
    from app.services.inventory_imports import InventoryImports

    if not (file.filename or "").lower().endswith(".csv"):
        raise ValidationError("Upload a CSV file; XLSX is a future extension")
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValidationError("CSV file exceeds 2 MB")
    result = await InventoryImports(session, actor).preview(
        kind, data, file.filename or "inventory.csv"
    )

    from starlette.concurrency import run_in_threadpool
    from app.models.document_library import LibraryDocument

    stored = await run_in_threadpool(
        storage.save,
        f"documents/{actor.organization_id}/imports",
        data,
        file.filename or "inventory.csv",
        "text/csv",
    )
    try:
        session.add(
            LibraryDocument(
                organization_id=actor.organization_id,
                source_type="inventory_imports",
                source_id=result["id"],
                title=file.filename or "Inventory import",
                category="Inventory",
                tags=["import", kind],
                storage_path=stored.relative_path,
                file_name=stored.filename,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                owner_id=actor.id,
                visibility="PRIVATE",
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await run_in_threadpool(storage.delete, stored.relative_path)
        raise
    return result


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


@operational_router.get("/suppliers")
async def list_suppliers_alias(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await InventoryQueries(session, actor).listing(
        "suppliers", {"page": page, "page_size": page_size, "search": search}
    )
