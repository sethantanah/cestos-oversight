"""Read-only field equipment access through current project assignments."""

from datetime import UTC, date, datetime

from sqlalchemy import func, literal, or_, select, union_all

from app.core.exceptions import NotFoundError
from app.models import Asset, AssetAssignment, EmployeeAssignment, Project
from app.models.asset import AssetMeterReading
from app.models.maintenance_hse import MaintenanceWorkOrder
from app.models.operational_logs import AssetFuelLog, AssetMaintenanceJob
from app.services.field_work import own_employee_ids


def assigned_project_ids(actor):
    assignments = EmployeeAssignment.__table__
    own_ids = own_employee_ids(actor)
    active = select(assignments.c.project_id).where(
        assignments.c.organization_id == actor.organization_id,
        assignments.c.status == "ACTIVE",
        assignments.c.start_date <= date.today(),
        or_(assignments.c.end_date.is_(None), assignments.c.end_date >= date.today()),
        or_(assignments.c.employee_id.in_(own_ids), assignments.c.supervisor_id.in_(own_ids)),
    )
    return select(Project.id).where(
        Project.organization_id == actor.organization_id,
        Project.archived_at.is_(None),
        Project.is_active.is_(True),
        or_(Project.id.in_(active), Project.project_manager_id.in_(own_ids)),
    )


async def require_project(session, actor, project_id):
    if not await session.scalar(assigned_project_ids(actor).where(Project.id == project_id)):
        raise NotFoundError("Assigned project not found")


def equipment_query(actor, project_id):
    now = datetime.now(UTC)
    assigned = select(AssetAssignment.asset_id).where(
        AssetAssignment.organization_id == actor.organization_id,
        AssetAssignment.project_id == project_id,
        AssetAssignment.status == "ACTIVE",
        AssetAssignment.assigned_at <= now,
        or_(AssetAssignment.returned_at.is_(None), AssetAssignment.returned_at > now),
    )
    return select(Asset).where(
        Asset.organization_id == actor.organization_id,
        Asset.archived_at.is_(None),
        Asset.is_active.is_(True),
        Asset.id.in_(assigned),
    )


def equipment_public(asset, project_id):
    return {
        key: getattr(asset, key, None)
        for key in (
            "id",
            "name",
            "asset_number",
            "serial_number",
            "make",
            "model",
            "status",
            "current_meter_reading",
            "meter_type",
            "year_of_manufacture",
        )
    } | {"assigned_project_id": project_id}


async def field_equipment(session, actor, project_id):
    await require_project(session, actor, project_id)
    assets = (await session.scalars(equipment_query(actor, project_id).order_by(Asset.name))).all()
    return [equipment_public(asset, project_id) for asset in assets]


async def equipment_history(session, actor, project_id, asset_id, kind, page=1, page_size=25):
    await require_project(session, actor, project_id)
    asset = await session.scalar(equipment_query(actor, project_id).where(Asset.id == asset_id))
    if not asset:
        raise NotFoundError("Equipment is not assigned to this project")
    if kind == "maintenance":
        queries = []
        for model, type_column, source in (
            (AssetMaintenanceJob, AssetMaintenanceJob.maintenance_type, "maintenance_job"),
            (MaintenanceWorkOrder, MaintenanceWorkOrder.work_type, "work_order"),
        ):
            query = select(
                model.id,
                model.title,
                model.description,
                model.status,
                model.priority,
                type_column.label("maintenance_type"),
                model.scheduled_date,
                model.completed_at,
                func.coalesce(
                    model.field_notes,
                    model.completion_notes if model is AssetMaintenanceJob else model.notes,
                ).label("notes"),
                model.approved_at,
                literal(source).label("source"),
            ).where(model.organization_id == actor.organization_id, model.asset_id == asset_id)
            if model is MaintenanceWorkOrder:
                query = query.where(model.archived_at.is_(None), model.is_active.is_(True))
            queries.append(query)
        combined = union_all(*queries).subquery()
        query = select(combined).order_by(combined.c.scheduled_date.desc(), combined.c.id)
    elif kind == "fuel":
        query = (
            select(
                AssetFuelLog.id,
                AssetFuelLog.recorded_at,
                AssetFuelLog.fuel_type,
                AssetFuelLog.quantity_litres,
                AssetFuelLog.meter_reading,
                AssetFuelLog.supplier,
                AssetFuelLog.notes,
            )
            .where(
                AssetFuelLog.organization_id == actor.organization_id,
                AssetFuelLog.asset_id == asset_id,
            )
            .order_by(AssetFuelLog.recorded_at.desc(), AssetFuelLog.id)
        )
    else:
        query = (
            select(
                AssetMeterReading.id,
                AssetMeterReading.recorded_at,
                AssetMeterReading.reading,
                AssetMeterReading.reading_type,
                AssetMeterReading.source,
                AssetMeterReading.notes,
            )
            .where(
                AssetMeterReading.organization_id == actor.organization_id,
                AssetMeterReading.asset_id == asset_id,
            )
            .order_by(AssetMeterReading.recorded_at.desc(), AssetMeterReading.id)
        )
    total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    records = (
        await session.execute(query.offset((page - 1) * page_size).limit(page_size))
    ).mappings()
    return {
        "asset": equipment_public(asset, project_id),
        "items": [dict(row) for row in records],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
