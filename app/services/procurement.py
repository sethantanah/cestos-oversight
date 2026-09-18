import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.procurement import PoStatus, PurchaseOrder, PurchaseOrderItem
from app.schemas.procurement import (
    PurchaseOrderCreate,
    ReceiveGoodsRequest,
)
from app.services.counters import next_business_number


async def create_purchase_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: PurchaseOrderCreate,
    actor_id: uuid.UUID | None = None,
) -> PurchaseOrder:
    po_number = await next_business_number(session, organization_id, "purchase_order")
    po = PurchaseOrder(
        organization_id=organization_id,
        po_number=po_number,
        supplier_id=payload.supplier_id,
        project_id=payload.project_id,
        request_id=payload.request_id,
        status=PoStatus.APPROVED,
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
                description=item.description,
                quantity_ordered=item.quantity_ordered,
                quantity_received=Decimal("0.0"),
                unit_price=item.unit_price,
                total_price=item_tot,
            )
        )
    po.total_amount = total_amt
    session.add(po)
    await session.commit()
    return await get_purchase_order(session, organization_id, po.id)  # type: ignore[return-value]


async def get_purchase_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    po_id: uuid.UUID,
) -> PurchaseOrder | None:
    return await session.scalar(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
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
        .options(selectinload(PurchaseOrder.items))
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


async def receive_goods(
    session: AsyncSession,
    organization_id: uuid.UUID,
    po_id: uuid.UUID,
    payload: ReceiveGoodsRequest,
) -> PurchaseOrder:
    po = await get_purchase_order(session, organization_id, po_id)
    if not po:
        raise ValueError(f"Purchase Order {po_id} not found.")

    all_fully_received = True
    any_received = False

    for item in po.items:
        if item.id in payload.item_receipts:
            qty_add = payload.item_receipts[item.id]
            item.quantity_received += qty_add

        if item.quantity_received > 0:
            any_received = True
        if item.quantity_received < item.quantity_ordered:
            all_fully_received = False

    if all_fully_received:
        po.status = PoStatus.RECEIVED
    elif any_received:
        po.status = PoStatus.PARTIALLY_RECEIVED

    await session.commit()
    return await get_purchase_order(session, organization_id, po.id)  # type: ignore[return-value]
