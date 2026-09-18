import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_records import AssetDefect
from app.models.drilling_commercial import CostCategory, CostSubledgerEntry
from app.models.maintenance_hse import (
    MaintenanceWorkOrder,
    WorkOrderCostLine,
    WorkOrderStatus,
)
from app.schemas.maintenance_hse import (
    AssetReliabilitySummaryResponse,
    CompleteWorkOrderRequest,
    MaintenanceWorkOrderCreate,
    MaintenanceWorkOrderUpdate,
    WorkOrderCostLineCreate,
)
from app.services.counters import next_business_number

UTC = timezone.utc


async def create_work_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: MaintenanceWorkOrderCreate,
    actor_id: uuid.UUID | None = None,
) -> MaintenanceWorkOrder:
    wo_number = await next_business_number(session, organization_id, "maintenance_work_order")
    wo = MaintenanceWorkOrder(
        organization_id=organization_id,
        wo_number=wo_number,
        asset_id=payload.asset_id,
        project_id=payload.project_id,
        defect_id=payload.defect_id,
        inspection_id=payload.inspection_id,
        title=payload.title,
        description=payload.description,
        work_type=payload.work_type,
        priority=payload.priority,
        status=WorkOrderStatus.OPEN,
        failure_taxonomy=payload.failure_taxonomy,
        assigned_technician_id=payload.assigned_technician_id,
        scheduled_date=payload.scheduled_date,
        meter_reading=payload.meter_reading,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    for cl in payload.cost_lines:
        tot = cl.quantity * cl.unit_cost
        wo.cost_lines.append(
            WorkOrderCostLine(
                organization_id=organization_id,
                cost_type=cl.cost_type.upper(),
                description=cl.description,
                part_number=cl.part_number,
                quantity=cl.quantity,
                unit_cost=cl.unit_cost,
                total_cost=tot,
                currency=cl.currency,
            )
        )
    session.add(wo)
    await session.commit()
    return await get_work_order(session, organization_id, wo.id)  # type: ignore[return-value]


async def get_work_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    wo_id: uuid.UUID,
) -> MaintenanceWorkOrder | None:
    return await session.scalar(
        select(MaintenanceWorkOrder)
        .options(selectinload(MaintenanceWorkOrder.cost_lines))
        .where(
            MaintenanceWorkOrder.id == wo_id,
            MaintenanceWorkOrder.organization_id == organization_id,
            MaintenanceWorkOrder.archived_at.is_(None),
        )
    )


async def list_work_orders(
    session: AsyncSession,
    organization_id: uuid.UUID,
    asset_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: WorkOrderStatus | None = None,
) -> list[MaintenanceWorkOrder]:
    stmt = (
        select(MaintenanceWorkOrder)
        .options(selectinload(MaintenanceWorkOrder.cost_lines))
        .where(
            MaintenanceWorkOrder.organization_id == organization_id,
            MaintenanceWorkOrder.archived_at.is_(None),
        )
    )
    if asset_id:
        stmt = stmt.where(MaintenanceWorkOrder.asset_id == asset_id)
    if project_id:
        stmt = stmt.where(MaintenanceWorkOrder.project_id == project_id)
    if status:
        stmt = stmt.where(MaintenanceWorkOrder.status == status)

    stmt = stmt.order_by(MaintenanceWorkOrder.created_at.desc())
    return list((await session.scalars(stmt)).all())


async def add_cost_line_to_work_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    wo_id: uuid.UUID,
    payload: WorkOrderCostLineCreate,
) -> WorkOrderCostLine:
    wo = await get_work_order(session, organization_id, wo_id)
    if not wo:
        raise ValueError(f"Work order {wo_id} not found.")

    tot = payload.quantity * payload.unit_cost
    line = WorkOrderCostLine(
        organization_id=organization_id,
        work_order_id=wo_id,
        cost_type=payload.cost_type.upper(),
        description=payload.description,
        part_number=payload.part_number,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        total_cost=tot,
        currency=payload.currency,
    )
    session.add(line)
    await session.commit()
    await session.refresh(line)
    return line


async def complete_work_order(
    session: AsyncSession,
    organization_id: uuid.UUID,
    wo_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CompleteWorkOrderRequest,
) -> MaintenanceWorkOrder:
    wo = await get_work_order(session, organization_id, wo_id)
    if not wo:
        raise ValueError(f"Work order {wo_id} not found.")

    if wo.status == WorkOrderStatus.COMPLETED:
        return wo

    wo.status = WorkOrderStatus.COMPLETED
    wo.completed_at = datetime.now(UTC)
    wo.completed_by_id = user_id

    if payload.root_cause:
        wo.root_cause = payload.root_cause
    if payload.remedy:
        wo.remedy = payload.remedy
    if payload.downtime_hours:
        wo.downtime_hours = payload.downtime_hours
    if payload.estimated_lost_contribution:
        wo.estimated_lost_contribution = payload.estimated_lost_contribution
    if payload.notes:
        wo.notes = (wo.notes or "") + f"\nCompletion notes: {payload.notes}"

    # Resolve linked defect if applicable
    if wo.defect_id:
        defect = await session.get(AssetDefect, wo.defect_id)
        if defect and defect.organization_id == organization_id:
            defect.status = "RESOLVED"
            defect.resolved_at = datetime.now(UTC)
            defect.notes = (defect.notes or "") + f"\nResolved via Work Order {wo.wo_number}"

    # Auto-post cost lines to CostSubledgerEntry
    for line in wo.cost_lines:
        if not line.posted_to_subledger:
            category = (
                CostCategory.MAINTENANCE_PARTS
                if line.cost_type.upper() == "PARTS"
                else CostCategory.LABOUR
            )
            subledger_entry = CostSubledgerEntry(
                organization_id=organization_id,
                project_id=wo.project_id or wo.asset_id,  # fallback if project_id not set
                rig_id=wo.asset_id,
                cost_category=category,
                description=f"WO {wo.wo_number}: {line.description}",
                quantity=line.quantity,
                unit_of_measure="EA" if category == CostCategory.MAINTENANCE_PARTS else "HRS",
                unit_cost=line.unit_cost,
                total_cost=line.total_cost,
                currency=line.currency,
                exchange_rate_to_base=Decimal("1.000000"),
                total_cost_base=line.total_cost,
                source_entity_type="maintenance_work_order",
                source_entity_id=wo.id,
                posted_at=datetime.now(UTC),
                created_by_id=user_id,
                updated_by_id=user_id,
            )
            session.add(subledger_entry)
            line.posted_to_subledger = True

    await session.commit()
    res = await get_work_order(session, organization_id, wo.id)
    assert res is not None
    return res


async def get_asset_reliability_summary(
    session: AsyncSession,
    organization_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> AssetReliabilitySummaryResponse:
    asset = await session.get(Asset, asset_id)
    if not asset or asset.organization_id != organization_id:
        raise ValueError(f"Asset {asset_id} not found.")

    wo_stmt = select(MaintenanceWorkOrder).where(
        MaintenanceWorkOrder.organization_id == organization_id,
        MaintenanceWorkOrder.asset_id == asset_id,
        MaintenanceWorkOrder.archived_at.is_(None),
    )
    work_orders = list((await session.scalars(wo_stmt)).all())

    total_wos = len(work_orders)
    open_wos = sum(1 for wo in work_orders if wo.status in (WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.WAITING_PARTS))
    completed_wos = sum(1 for wo in work_orders if wo.status == WorkOrderStatus.COMPLETED)
    total_downtime = sum(wo.downtime_hours for wo in work_orders)

    # Calculate total maintenance costs from work orders
    total_maint_cost = Decimal("0.0")
    for wo in work_orders:
        for cl in wo.cost_lines:
            total_maint_cost += cl.total_cost

    # Taxonomy counts
    tax_counts: dict[str, int] = {}
    for wo in work_orders:
        if wo.failure_taxonomy:
            key = wo.failure_taxonomy.value if hasattr(wo.failure_taxonomy, "value") else str(wo.failure_taxonomy)
            tax_counts[key] = tax_counts.get(key, 0) + 1

    # Standard operating baseline: 720 hours / month
    period_hours = Decimal("720.0")
    avail_pct = max(Decimal("0.0"), (period_hours - total_downtime) / period_hours * Decimal("100.0"))
    cost_per_hr = (total_maint_cost / (period_hours - total_downtime)) if (period_hours - total_downtime) > 0 else Decimal("0.0")
    mttr = (total_downtime / Decimal(str(completed_wos))) if completed_wos > 0 else None

    return AssetReliabilitySummaryResponse(
        asset_id=asset_id,
        asset_name=asset.name,
        total_work_orders=total_wos,
        open_work_orders=open_wos,
        completed_work_orders=completed_wos,
        total_downtime_hours=float(total_downtime),
        availability_pct=round(float(avail_pct), 2),
        total_maintenance_cost=float(total_maint_cost),
        maintenance_cost_per_hour=round(float(cost_per_hr), 2),
        mtbf_hours=float(period_hours / Decimal(str(completed_wos))) if completed_wos > 0 else None,
        mttr_hours=round(float(mttr), 2) if mttr is not None else None,
        failure_count_by_taxonomy=tax_counts,
    )
