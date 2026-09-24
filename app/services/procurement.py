import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.procurement import PoStatus, PurchaseOrder, PurchaseOrderItem
from app.models.operational_logs import FuelSupplier
from app.schemas.procurement import (
    PurchaseOrderCreate,
    PurchaseOrderUpdate,
    ReceiveGoodsRequest,
)
from app.services.counters import next_business_number
from app.services.notification_schedules import emit_configured_event


async def create_purchase_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: PurchaseOrderCreate,
    actor_id: uuid.UUID | None = None,
) -> PurchaseOrder:
    supplier = None
    if payload.supplier_id:
        supplier = await session.scalar(
            select(FuelSupplier).where(
                FuelSupplier.id == payload.supplier_id,
                FuelSupplier.organization_id == organization_id,
            )
        )
        if not supplier:
            raise ValueError("Supplier not found in this organization")
    else:
        supplier_name = (payload.supplier_name or "").strip()
        supplier = await session.scalar(
            select(FuelSupplier).where(
                FuelSupplier.organization_id == organization_id,
                func.lower(FuelSupplier.name) == supplier_name.lower(),
            )
        )
        if not supplier:
            supplier = FuelSupplier(
                organization_id=organization_id,
                name=supplier_name,
                created_by_id=actor_id,
            )
            session.add(supplier)
            await session.flush()
    po_number = await next_business_number(session, organization_id, "purchase_order")
    po = PurchaseOrder(
        organization_id=organization_id,
        po_number=po_number,
        supplier_id=supplier.id,
        project_id=payload.project_id,
        request_id=payload.request_id,
        category=(payload.category or "").strip() or None,
        status=PoStatus.DRAFT if payload.save_as_draft else PoStatus.WAITING_APPROVAL,
        currency=payload.currency,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    total_amt = Decimal("0.0")
    for item in payload.items:
        item_tot = item.quantity_ordered * item.unit_price
        total_amt += item_tot
        po.items.append(
            PurchaseOrderItem(
                organization_id=organization_id,
                inventory_item_id=item.inventory_item_id,
                item_name=item.item_name,
                description=item.description,
                quantity_ordered=item.quantity_ordered,
                quantity_received=Decimal("0.0"),
                unit_price=item.unit_price,
                total_price=item_tot,
            )
        )
    po.total_amount = total_amt if total_amt > 0 else (payload.total_amount or Decimal("0"))
    session.add(po)
    await session.flush()
    if po.status == PoStatus.WAITING_APPROVAL:
        await emit_configured_event(
            session,
            organization_id,
            "FINANCE_PURCHASE_ORDER_THRESHOLD",
            f"purchase-order:{po.id}:created",
            f"Purchase order {po.po_number} for {po.currency} {po.total_amount:,.2f} is awaiting approval.",
            po.total_amount,
        )
    await session.commit()
    return await get_purchase_order(session, organization_id, po.id)  # type: ignore[return-value]


async def get_purchase_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    po_id: uuid.UUID,
) -> PurchaseOrder | None:
    return await session.scalar(
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.items),
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.created_by_user),
        )
        .where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.archived_at.is_(None),
        )
    )


async def list_purchase_orders(
    session: AsyncSession,
    organization_id: uuid.UUID,
    supplier_id: uuid.UUID | None = None,
    status: PoStatus | None = None,
) -> list[PurchaseOrder]:
    stmt = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.items),
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.created_by_user),
        )
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.archived_at.is_(None),
        )
    )
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)

    stmt = stmt.order_by(PurchaseOrder.created_at.desc())
    return list((await session.scalars(stmt)).all())


async def update_purchase_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    po_id: uuid.UUID,
    payload: PurchaseOrderUpdate,
    actor_id: uuid.UUID,
) -> PurchaseOrder:
    po = await get_purchase_order(session, organization_id, po_id)
    if not po:
        raise ValueError(f"Purchase Order {po_id} not found.")
    if any(item.quantity_received > 0 for item in po.items):
        raise ValueError("A purchase order cannot be edited after goods have been received")

    supplier_name = payload.supplier_name.strip()
    if not supplier_name:
        raise ValueError("Supplier name is required")
    supplier = await session.scalar(
        select(FuelSupplier).where(
            FuelSupplier.organization_id == organization_id,
            func.lower(FuelSupplier.name) == supplier_name.lower(),
        )
    )
    if not supplier:
        supplier = FuelSupplier(
            organization_id=organization_id,
            name=supplier_name,
            created_by_id=actor_id,
        )
        session.add(supplier)
        await session.flush()

    po.supplier = supplier
    po.project_id = payload.project_id
    po.category = (payload.category or "").strip() or None
    po.currency = payload.currency
    po.notes = payload.notes
    po.updated_by_id = actor_id
    po.items.clear()
    total_amount = Decimal("0")
    for item in payload.items:
        line_total = item.quantity_ordered * item.unit_price
        total_amount += line_total
        po.items.append(
            PurchaseOrderItem(
                organization_id=organization_id,
                inventory_item_id=item.inventory_item_id,
                item_name=item.item_name,
                description=item.description,
                quantity_ordered=item.quantity_ordered,
                quantity_received=Decimal("0"),
                unit_price=item.unit_price,
                total_price=line_total,
            )
        )
    po.total_amount = total_amount if total_amount > 0 else (payload.total_amount or Decimal("0"))
    await session.commit()
    return await get_purchase_order(session, organization_id, po.id)  # type: ignore[return-value]


async def receive_goods(
    session: AsyncSession,
    organization_id: uuid.UUID,
    po_id: uuid.UUID,
    payload: ReceiveGoodsRequest,
) -> PurchaseOrder:
    po = await get_purchase_order(session, organization_id, po_id)
    if not po:
        raise ValueError(f"Purchase Order {po_id} not found.")
    if po.status in {PoStatus.DRAFT, PoStatus.WAITING_APPROVAL}:
        raise ValueError("The purchase order must be approved before goods can be received")
    if po.status in {PoStatus.RECEIVED, PoStatus.CLOSED, PoStatus.CANCELLED}:
        raise ValueError("This purchase order is no longer accepting goods")

    all_fully_received = True
    any_received = False
    received_now = Decimal("0")
    received_lines = []

    for item in po.items:
        if item.id in payload.item_receipts:
            qty_add = payload.item_receipts[item.id]
            if qty_add < 0 or item.quantity_received + qty_add > item.quantity_ordered:
                raise ValueError(f"Receipt quantity for {item.description} exceeds the outstanding quantity")
            item.quantity_received += qty_add
            if qty_add > 0:
                received_now += qty_add
                received_lines.append(f"{item.item_name or item.description}: {qty_add}")

        if item.quantity_received > 0:
            any_received = True
        if item.quantity_received < item.quantity_ordered:
            all_fully_received = False

    if all_fully_received:
        po.status = PoStatus.RECEIVED
    elif any_received:
        po.status = PoStatus.PARTIALLY_RECEIVED

    if received_now > 0:
        await emit_configured_event(
            session,
            organization_id,
            "FINANCE_PURCHASE_ORDER_GOODS_RECEIVED",
            f"purchase-order:{po.id}:goods-received:{uuid.uuid4()}",
            f"Goods receipt recorded for purchase order {po.po_number} ({po.currency} {po.total_amount:,.2f}). "
            f"Received: {', '.join(received_lines)}. Status: {getattr(po.status, 'value', po.status)}.",
            po.total_amount,
        )
    await session.commit()
    return await get_purchase_order(session, organization_id, po.id)  # type: ignore[return-value]


async def approve_purchase_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    po_id: uuid.UUID,
    approver_id: uuid.UUID,
) -> PurchaseOrder:
    from datetime import UTC, datetime

    po = await get_purchase_order(session, organization_id, po_id)
    if not po:
        raise ValueError(f"Purchase Order {po_id} not found")
    if po.status != PoStatus.WAITING_APPROVAL:
        raise ValueError("Only purchase orders waiting for approval can be approved")
    po.status = PoStatus.APPROVED
    po.approved_by_id = approver_id
    po.approved_at = datetime.now(UTC)
    po.updated_by_id = approver_id
    await session.commit()
    return await get_purchase_order(session, organization_id, po.id)  # type: ignore[return-value]
