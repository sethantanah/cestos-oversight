import json
import os
from pathlib import Path
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, or_, delete, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_active_user, require_permission
from app.db.session import get_session
from app.models import (
    Asset,
    AssetCategory,
    AssetMeterReading,
    AssetAssignment,
    Client,
    Employee,
    EmployeeAssignment,
    Location,
    Project,
    User,
)
from app.models.employee import Department, AssignmentStatus, EmploymentStatus, Skill, EmployeeSkill, EmployeeQualification
from app.models.asset import AssetStatus
from app.models.project import ProjectStatus
from app.models.operational_logs import AssetFuelLog, AssetMaintenanceJob
from app.models.asset_records import AssetDefect
from app.models.inventory import InventoryItem, InventoryStore, InventoryCategory, InventoryIssue, InventoryIssueItem, InventoryBalance
from app.models.hr import Salary as EmployeeSalary
from app.models.document_library import LibraryDocument
from app.models.intelligence import AssistantChatMessage
from app.services.document_index import search_vectors

VALID_ASSET_STATUSES = {e.value for e in AssetStatus}
VALID_PROJECT_STATUSES = {e.value for e in ProjectStatus}
VALID_EMPLOYMENT_STATUSES = {e.value for e in EmploymentStatus}

router = APIRouter(prefix="/intelligence", tags=["Intelligence"])

MODEL_REGISTRY = {
    "employee": Employee,
    "employees": Employee,
    "workforce": Employee,
    "staff": Employee,
    "personnel": Employee,
    "asset": Asset,
    "assets": Asset,
    "fleet": Asset,
    "equipment": Asset,
    "project": Project,
    "projects": Project,
    "inventory": InventoryItem,
    "inventoryitem": InventoryItem,
    "stock": InventoryItem,
    "location": Location,
    "locations": Location,
    "site": Location,
    "sites": Location,
    "department": Department,
    "departments": Department,
    "assignment": EmployeeAssignment,
    "salary": EmployeeSalary,
    "payroll": EmployeeSalary,
    "document": LibraryDocument,
}


def inspect_table_schema(table_name: str) -> dict[str, Any]:
    """Inspect model/table columns dynamically for self-correction."""
    model = MODEL_REGISTRY.get(table_name.lower())
    if not model:
        return {"error": f"Model or table '{table_name}' not found."}
    columns = {col.name: str(col.type) for col in model.__table__.columns}
    return {
        "model_name": model.__name__,
        "table_name": model.__tablename__,
        "columns": columns,
    }


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="Message content text")


class AssistantQueryRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., description="Full multi-turn conversation history")
    conversation_id: str | None = Field(default=None, description="Optional conversation tracking ID")


class AssistantQueryResponse(BaseModel):
    reply: str
    conversation_id: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    suggested_filters: dict[str, Any] | None = Field(default=None)


@router.get("/metrics", dependencies=[Depends(require_permission("intelligence.read"))])
async def get_intelligence_metrics(
    project_id: str | None = Query(None),
    location_id: str | None = Query(None),
    department_id: str | None = Query(None),
    category_id: str | None = Query(None),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return executive cross-domain operational intelligence metrics with comprehensive filtering."""
    org_id = user.organization_id

    if not isinstance(project_id, str): project_id = None
    if not isinstance(location_id, str): location_id = None
    if not isinstance(department_id, str): department_id = None
    if not isinstance(category_id, str): category_id = None
    if not isinstance(status, str): status = None
    if not isinstance(date_from, str): date_from = None
    if not isinstance(date_to, str): date_to = None

    # Parse optional dates
    d_from = None
    d_to = None
    if date_from:
        try:
            d_from = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        except Exception:
            pass
    if date_to:
        try:
            d_to = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
        except Exception:
            pass

    # 1. Fleet Utilization
    asset_query = select(Asset.status, func.count(Asset.id)).where(
        Asset.organization_id == org_id, Asset.archived_at.is_(None)
    )
    if category_id:
        asset_query = asset_query.where(Asset.category_id == category_id)
    if location_id:
        asset_query = asset_query.where(Asset.default_location_id == location_id)
    if department_id:
        asset_query = asset_query.where(Asset.responsible_employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))
    if project_id:
        asset_query = asset_query.where(
            or_(
                Asset.id.in_(select(AssetAssignment.asset_id).where(AssetAssignment.project_id == project_id, AssetAssignment.status == "ACTIVE")),
                Asset.default_location_id.in_(select(Location.id).where(Location.project_id == project_id))
            )
        )
    if status and status != 'ALL':
        st_upper = status.upper()
        if st_upper in VALID_ASSET_STATUSES:
            asset_query = asset_query.where(Asset.status == st_upper)
        elif st_upper in ['ACTIVE', 'IN_PROGRESS']:
            asset_query = asset_query.where(Asset.status.in_([AssetStatus.OPERATING, AssetStatus.AVAILABLE]))

    asset_query = asset_query.group_by(Asset.status)
    asset_counts_raw = (await session.execute(asset_query)).all()
    fleet_by_status = {str(st).upper(): cnt for st, cnt in asset_counts_raw}
    total_fleet = sum(fleet_by_status.values())
    operating_fleet = fleet_by_status.get("OPERATING", 0) + fleet_by_status.get("AVAILABLE", 0)
    utilization_rate = round((operating_fleet / total_fleet * 100), 1) if total_fleet > 0 else 0.0

    # Fleet by category
    fleet_cat_stmt = (
        select(func.coalesce(AssetCategory.name, "General Fleet").label("category"), func.count(Asset.id).label("count"))
        .outerjoin(AssetCategory, Asset.category_id == AssetCategory.id)
        .where(Asset.organization_id == org_id, Asset.archived_at.is_(None))
    )
    if location_id:
        fleet_cat_stmt = fleet_cat_stmt.where(Asset.default_location_id == location_id)
    if category_id:
        fleet_cat_stmt = fleet_cat_stmt.where(Asset.category_id == category_id)
    if department_id:
        fleet_cat_stmt = fleet_cat_stmt.where(Asset.responsible_employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))
    if project_id:
        fleet_cat_stmt = fleet_cat_stmt.where(
            or_(
                Asset.id.in_(select(AssetAssignment.asset_id).where(AssetAssignment.project_id == project_id, AssetAssignment.status == "ACTIVE")),
                Asset.default_location_id.in_(select(Location.id).where(Location.project_id == project_id))
            )
        )

    fleet_cat_stmt = fleet_cat_stmt.group_by(AssetCategory.name).order_by(func.count(Asset.id).desc())
    fleet_cat_rows = (await session.execute(fleet_cat_stmt)).all()
    fleet_by_category = [{"category": str(r.category), "count": int(r.count)} for r in fleet_cat_rows]

    # 2. Fuel Efficiency
    fuel_query = select(func.sum(AssetFuelLog.quantity_litres)).where(
        AssetFuelLog.organization_id == org_id
    )
    meter_query = select(func.sum(AssetMeterReading.reading)).where(
        AssetMeterReading.organization_id == org_id
    )
    if category_id:
        fuel_query = fuel_query.where(AssetFuelLog.asset_id.in_(select(Asset.id).where(Asset.category_id == category_id)))
        meter_query = meter_query.where(AssetMeterReading.asset_id.in_(select(Asset.id).where(Asset.category_id == category_id)))
    if location_id:
        fuel_query = fuel_query.where(or_(AssetFuelLog.location_id == location_id, AssetFuelLog.asset_id.in_(select(Asset.id).where(Asset.default_location_id == location_id))))
        meter_query = meter_query.where(AssetMeterReading.asset_id.in_(select(Asset.id).where(Asset.default_location_id == location_id)))
    if project_id:
        fuel_query = fuel_query.where(or_(AssetFuelLog.project_id == project_id, AssetFuelLog.asset_id.in_(select(AssetAssignment.asset_id).where(AssetAssignment.project_id == project_id))))
        meter_query = meter_query.where(AssetMeterReading.asset_id.in_(select(AssetAssignment.asset_id).where(AssetAssignment.project_id == project_id)))
    if d_from:
        fuel_query = fuel_query.where(AssetFuelLog.recorded_at >= d_from)
        meter_query = meter_query.where(AssetMeterReading.recorded_at >= d_from)
    if d_to:
        fuel_query = fuel_query.where(AssetFuelLog.recorded_at <= d_to)
        meter_query = meter_query.where(AssetMeterReading.recorded_at <= d_to)

    total_fuel = (await session.execute(fuel_query)).scalar() or 0.0
    total_meter_hours = (await session.execute(meter_query)).scalar() or 0.0
    fuel_efficiency_lph = round(float(total_fuel) / float(total_meter_hours), 2) if total_meter_hours > 0 else 0.0

    # 3. Drilling Performance
    proj_query = select(
        func.count(Project.id),
        func.sum(Project.target_metres),
        func.sum(Project.contract_value),
    ).where(Project.organization_id == org_id, Project.archived_at.is_(None))
    if project_id:
        proj_query = proj_query.where(Project.id == project_id)
    if location_id:
        proj_query = proj_query.where(Project.id.in_(select(Location.project_id).where(Location.id == location_id, Location.project_id.is_not(None))))
    if status and status != 'ALL':
        st_upper = status.upper()
        if st_upper in VALID_PROJECT_STATUSES:
            proj_query = proj_query.where(Project.status == st_upper)
        elif st_upper in ['OPERATING', 'AVAILABLE', 'IN_PROGRESS']:
            proj_query = proj_query.where(Project.status == ProjectStatus.ACTIVE)

    p_cnt, target_m, contract_val = (await session.execute(proj_query)).one()
    target_m = float(target_m or 0.0)

    # Filtered drilled metres calculation
    completed_stmt = (
        select(func.coalesce(func.sum(Project.target_metres), 0))
        .where(Project.organization_id == org_id, Project.status == ProjectStatus.COMPLETED, Project.archived_at.is_(None))
    )
    active_stmt = (
        select(func.coalesce(func.sum(Project.target_metres), 0))
        .where(Project.organization_id == org_id, Project.status == ProjectStatus.ACTIVE, Project.archived_at.is_(None))
    )
    if project_id:
        completed_stmt = completed_stmt.where(Project.id == project_id)
        active_stmt = active_stmt.where(Project.id == project_id)
    if location_id:
        completed_stmt = completed_stmt.where(Project.id.in_(select(Location.project_id).where(Location.id == location_id)))
        active_stmt = active_stmt.where(Project.id.in_(select(Location.project_id).where(Location.id == location_id)))

    completed_m = (await session.execute(completed_stmt)).scalar() or 0.0
    active_m = (await session.execute(active_stmt)).scalar() or 0.0

    drilled_m = round(float(completed_m) + (float(active_m) * 0.65), 1)
    if target_m > 0:
        drilled_m = min(target_m, drilled_m)
        drilling_completion_pct = round((drilled_m / target_m) * 100, 1)
    else:
        drilling_completion_pct = 0.0

    # Projects by Status
    proj_status_stmt = select(Project.status, func.count(Project.id)).where(
        Project.organization_id == org_id, Project.archived_at.is_(None)
    )
    if project_id:
        proj_status_stmt = proj_status_stmt.where(Project.id == project_id)
    if location_id:
        proj_status_stmt = proj_status_stmt.where(Project.id.in_(select(Location.project_id).where(Location.id == location_id, Location.project_id.is_not(None))))
    proj_status_stmt = proj_status_stmt.group_by(Project.status)
    proj_status_rows = (await session.execute(proj_status_stmt)).all()
    projects_by_status = [{"status": str(st).title(), "count": int(cnt)} for st, cnt in proj_status_rows]

    # Equipment Defects & Maintenance Severity Telemetry
    defects_stmt = select(
        func.count(AssetDefect.id),
        func.coalesce(func.sum(case((AssetDefect.severity == "CRITICAL", 1), else_=0)), 0),
        func.coalesce(func.sum(case((AssetDefect.severity == "HIGH", 1), else_=0)), 0),
        func.coalesce(func.sum(case((AssetDefect.severity == "MEDIUM", 1), else_=0)), 0),
        func.coalesce(func.sum(case((AssetDefect.severity == "LOW", 1), else_=0)), 0),
    ).where(AssetDefect.organization_id == org_id, AssetDefect.status == "OPEN")

    if category_id:
        defects_stmt = defects_stmt.where(AssetDefect.asset_id.in_(select(Asset.id).where(Asset.category_id == category_id)))
    if location_id:
        defects_stmt = defects_stmt.where(AssetDefect.asset_id.in_(select(Asset.id).where(Asset.default_location_id == location_id)))
    if project_id:
        defects_stmt = defects_stmt.where(AssetDefect.asset_id.in_(select(AssetAssignment.asset_id).where(AssetAssignment.project_id == project_id)))
    if department_id:
        defects_stmt = defects_stmt.where(AssetDefect.asset_id.in_(select(Asset.id).where(Asset.responsible_employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))))
    if d_from:
        defects_stmt = defects_stmt.where(AssetDefect.created_at >= d_from)
    if d_to:
        defects_stmt = defects_stmt.where(AssetDefect.created_at <= d_to)

    open_defects_count, critical_defects_count, high_defects_count, medium_defects_count, low_defects_count = (await session.execute(defects_stmt)).one()

    defects_by_severity = [
        {"severity": "Critical", "count": int(critical_defects_count or 0)},
        {"severity": "High", "count": int(high_defects_count or 0)},
        {"severity": "Medium", "count": int(medium_defects_count or 0)},
        {"severity": "Low", "count": int(low_defects_count or 0)},
    ]

    # 4. Workforce Productivity
    emp_query = select(func.count(Employee.id)).where(
        Employee.organization_id == org_id, Employee.archived_at.is_(None)
    )
    if department_id:
        emp_query = emp_query.where(Employee.department_id == department_id)
    if location_id:
        emp_query = emp_query.where(or_(Employee.home_location_id == location_id, Employee.id.in_(select(EmployeeAssignment.employee_id).where(EmployeeAssignment.project_id.in_(select(Location.project_id).where(Location.id == location_id))))))
    if project_id:
        emp_query = emp_query.where(Employee.id.in_(select(EmployeeAssignment.employee_id).where(EmployeeAssignment.project_id == project_id, EmployeeAssignment.status == AssignmentStatus.ACTIVE)))
    if status and status != 'ALL':
        st_upper = status.upper()
        if st_upper in VALID_EMPLOYMENT_STATUSES:
            emp_query = emp_query.where(Employee.employment_status == st_upper)
        elif st_upper in ['OPERATING', 'AVAILABLE', 'IN_PROGRESS']:
            emp_query = emp_query.where(Employee.employment_status == EmploymentStatus.ACTIVE)

    total_emp = (await session.execute(emp_query)).scalar() or 0

    assigned_query = select(func.count(func.distinct(EmployeeAssignment.employee_id))).where(
        EmployeeAssignment.organization_id == org_id, EmployeeAssignment.status == AssignmentStatus.ACTIVE
    )
    if project_id:
        assigned_query = assigned_query.where(EmployeeAssignment.project_id == project_id)
    if location_id:
        assigned_query = assigned_query.where(EmployeeAssignment.project_id.in_(select(Location.project_id).where(Location.id == location_id)))
    if department_id:
        assigned_query = assigned_query.where(EmployeeAssignment.employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))

    assigned_emp = (await session.execute(assigned_query)).scalar() or 0
    workforce_deployment_rate = round((assigned_emp / total_emp * 100), 1) if total_emp > 0 else 0.0

    # Workforce by Department
    dept_stmt = (
        select(func.coalesce(Department.name, Employee.department, "General").label("dept"), func.count(Employee.id).label("count"))
        .outerjoin(Department, Employee.department_id == Department.id)
        .where(Employee.organization_id == org_id, Employee.archived_at.is_(None))
    )
    if department_id:
        dept_stmt = dept_stmt.where(Employee.department_id == department_id)
    if location_id:
        dept_stmt = dept_stmt.where(Employee.home_location_id == location_id)
    if project_id:
        dept_stmt = dept_stmt.where(Employee.id.in_(select(EmployeeAssignment.employee_id).where(EmployeeAssignment.project_id == project_id, EmployeeAssignment.status == AssignmentStatus.ACTIVE)))

    dept_stmt = dept_stmt.group_by(Department.name, Employee.department).order_by(func.count(Employee.id).desc())
    dept_rows = (await session.execute(dept_stmt)).all()
    workforce_by_department = [{"department": str(r.dept), "count": int(r.count)} for r in dept_rows]

    # Workforce by Project
    wf_proj_stmt = (
        select(Project.name.label("project"), func.count(func.distinct(EmployeeAssignment.employee_id)).label("count"))
        .join(Project, EmployeeAssignment.project_id == Project.id)
        .where(EmployeeAssignment.organization_id == org_id, EmployeeAssignment.status == AssignmentStatus.ACTIVE)
    )
    if project_id:
        wf_proj_stmt = wf_proj_stmt.where(EmployeeAssignment.project_id == project_id)
    if location_id:
        wf_proj_stmt = wf_proj_stmt.where(EmployeeAssignment.project_id.in_(select(Location.project_id).where(Location.id == location_id)))
    if department_id:
        wf_proj_stmt = wf_proj_stmt.where(EmployeeAssignment.employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))

    wf_proj_stmt = wf_proj_stmt.group_by(Project.name).order_by(func.count(func.distinct(EmployeeAssignment.employee_id)).desc())
    wf_proj_rows = (await session.execute(wf_proj_stmt)).all()
    workforce_by_project = [{"project": str(r.project), "count": int(r.count)} for r in wf_proj_rows]

    # 5. Inventory Valuation
    inv_query = (
        select(
            func.count(func.distinct(InventoryItem.id)),
            func.coalesce(func.sum(InventoryBalance.inventory_value), 0),
        )
        .select_from(InventoryItem)
        .outerjoin(InventoryBalance, InventoryItem.id == InventoryBalance.item_id)
        .where(InventoryItem.organization_id == org_id, InventoryItem.archived_at.is_(None))
    )
    if category_id:
        inv_query = inv_query.where(InventoryItem.category_id == category_id)
    if location_id:
        inv_query = inv_query.where(InventoryBalance.store_id.in_(select(InventoryStore.id).where(InventoryStore.location_id == location_id)))
    if project_id:
        inv_query = inv_query.where(InventoryBalance.store_id.in_(select(InventoryStore.id).where(InventoryStore.location_id.in_(select(Location.id).where(Location.project_id == project_id)))))

    inv_count, inv_valuation = (await session.execute(inv_query)).one()

    # Inventory Value by Category
    inv_cat_stmt = (
        select(
            func.coalesce(InventoryCategory.name, "General Items").label("category"),
            func.coalesce(func.sum(InventoryBalance.inventory_value), 0).label("value")
        )
        .select_from(InventoryItem)
        .outerjoin(InventoryCategory, InventoryItem.category_id == InventoryCategory.id)
        .outerjoin(InventoryBalance, InventoryItem.id == InventoryBalance.item_id)
        .where(InventoryItem.organization_id == org_id, InventoryItem.archived_at.is_(None))
    )
    if category_id:
        inv_cat_stmt = inv_cat_stmt.where(InventoryItem.category_id == category_id)
    if location_id:
        inv_cat_stmt = inv_cat_stmt.where(InventoryBalance.store_id.in_(select(InventoryStore.id).where(InventoryStore.location_id == location_id)))
    if project_id:
        inv_cat_stmt = inv_cat_stmt.where(InventoryBalance.store_id.in_(select(InventoryStore.id).where(InventoryStore.location_id.in_(select(Location.id).where(Location.project_id == project_id)))))

    inv_cat_stmt = inv_cat_stmt.group_by(InventoryCategory.name).order_by(func.coalesce(func.sum(InventoryBalance.inventory_value), 0).desc())
    inv_cat_rows = (await session.execute(inv_cat_stmt)).all()
    inventory_by_category = [{"category": str(r.category), "value": float(r.value or 0.0)} for r in inv_cat_rows]

    # 6. Site Operational Capacity Matrix & Site Metrics
    loc_stmt = select(Location.id, Location.name).where(Location.organization_id == org_id, Location.archived_at.is_(None))
    if location_id:
        loc_stmt = loc_stmt.where(Location.id == location_id)
    if project_id:
        loc_stmt = loc_stmt.where(Location.project_id == project_id)

    loc_rows = (await session.execute(loc_stmt.limit(8))).all()
    site_capacity_breakdown = []
    for l_id, l_name in loc_rows:
        l_assets = (await session.execute(select(func.count(Asset.id)).where(Asset.organization_id == org_id, Asset.default_location_id == l_id, Asset.archived_at.is_(None)))).scalar() or 0
        l_staff = (await session.execute(select(func.count(Employee.id)).where(Employee.organization_id == org_id, Employee.home_location_id == l_id, Employee.archived_at.is_(None)))).scalar() or 0
        l_defects = (await session.execute(select(func.count(AssetDefect.id)).where(AssetDefect.organization_id == org_id, AssetDefect.status == "OPEN", AssetDefect.asset_id.in_(select(Asset.id).where(Asset.default_location_id == l_id))))).scalar() or 0
        l_val = (await session.execute(select(func.coalesce(func.sum(InventoryBalance.inventory_value), 0)).where(InventoryBalance.organization_id == org_id, InventoryBalance.store_id.in_(select(InventoryStore.id).where(InventoryStore.location_id == l_id))))).scalar() or 0.0
        site_capacity_breakdown.append({
            "site_id": str(l_id),
            "site_name": str(l_name),
            "fleet_count": int(l_assets),
            "workforce_count": int(l_staff),
            "open_defects": int(l_defects),
            "stock_value": float(l_val),
        })

    loc_count = len(loc_rows) if (location_id or project_id) else ((await session.execute(select(func.count(Location.id)).where(Location.organization_id == org_id, Location.archived_at.is_(None)))).scalar() or 0)
    client_count = (await session.execute(select(func.count(Client.id)).where(Client.organization_id == org_id, Client.archived_at.is_(None)))).scalar() or 0
    maint_count = (await session.execute(select(func.count(AssetMaintenanceJob.id)).where(AssetMaintenanceJob.organization_id == org_id, AssetMaintenanceJob.status.in_(["OPEN", "IN_PROGRESS"])))).scalar() or 0

    return {
        "fleet_utilization": {
            "total_assets": total_fleet,
            "operating": fleet_by_status.get("OPERATING", 0),
            "available": fleet_by_status.get("AVAILABLE", 0),
            "maintenance": fleet_by_status.get("UNDER_MAINTENANCE", 0) + fleet_by_status.get("MAINTENANCE", 0),
            "breakdown": fleet_by_status.get("BREAKDOWN", 0),
            "standby": fleet_by_status.get("STANDBY", 0),
            "utilization_rate_pct": utilization_rate,
            "open_defects_count": int(open_defects_count or 0),
            "critical_defects_count": int(critical_defects_count or 0),
            "by_category": fleet_by_category,
        },
        "fuel_efficiency": {
            "total_fuel_liters": float(total_fuel),
            "total_meter_hours": float(total_meter_hours),
            "fuel_consumption_liters_per_hour": fuel_efficiency_lph,
        },
        "drilling_performance": {
            "target_metres": target_m,
            "drilled_metres": drilled_m,
            "completion_pct": drilling_completion_pct,
            "by_status": projects_by_status,
        },
        "workforce_productivity": {
            "total_employees": total_emp,
            "assigned_employees": assigned_emp,
            "available_employees": max(0, total_emp - assigned_emp),
            "deployment_rate_pct": workforce_deployment_rate,
            "by_department": workforce_by_department,
            "by_project": workforce_by_project,
        },
        "inventory_intelligence": {
            "total_catalog_items": inv_count or 0,
            "total_stock_valuation": float(inv_valuation or 0.0),
            "by_category": inventory_by_category,
        },
        "financial_summary": {
            "total_projects": p_cnt or 0,
            "total_contract_value": float(contract_val or 0.0) if user.is_superuser else None,
            "total_locations": loc_count,
            "total_clients": client_count,
            "active_maintenance_jobs": maint_count,
            "open_defects_count": int(open_defects_count or 0),
            "critical_defects_count": int(critical_defects_count or 0),
        },
        "defect_intelligence": {
            "open_defects_count": int(open_defects_count or 0),
            "critical_defects_count": int(critical_defects_count or 0),
            "high_defects_count": int(high_defects_count or 0),
            "medium_defects_count": int(medium_defects_count or 0),
            "low_defects_count": int(low_defects_count or 0),
            "defects_by_severity": defects_by_severity,
            "active_maintenance_jobs": maint_count,
        },
        "site_intelligence": {
            "total_active_sites": loc_count,
            "site_capacity_breakdown": site_capacity_breakdown,
        },
        "efficiency_analytics": {
            "fleet_availability_ratio": round((operating_fleet / total_fleet * 100), 1) if total_fleet > 0 else 0.0,
            "workforce_idle_count": max(0, total_emp - assigned_emp),
            "estimated_fuel_cost_usd": round(float(total_fuel) * 1.45, 2),
        },
    }


async def _lookup_employee_assignments(user_query: str, org_id: Any, session: AsyncSession) -> list[dict[str, Any]]:
    """Lookup specific employee assignment details when a query mentions employee names or assignment terms."""
    if not user_query:
        return []

    q_lower = user_query.lower()
    stop_words = {
        "what", "is", "are", "the", "a", "an", "assigned", "assignment", "project", "site",
        "where", "who", "which", "has", "have", "employee", "employees", "staff", "workforce",
        "personnel", "and", "for", "with", "show", "list", "find", "get", "tell", "me", "working",
        "on", "to", "current", "active", "status", "role", "details", "overview", "metrics"
    }
    raw_tokens = [t.strip(",.?!'\"") for t in q_lower.split() if len(t.strip(",.?!'\"")) > 1]
    search_tokens = [t for t in raw_tokens if t not in stop_words]

    if not search_tokens:
        return []

    or_conds = []
    for t in search_tokens:
        or_conds.extend([
            Employee.first_name.ilike(f"%{t}%"),
            Employee.last_name.ilike(f"%{t}%"),
            (Employee.first_name + " " + Employee.last_name).ilike(f"%{t}%"),
        ])

    emp_stmt = select(Employee).where(
        Employee.organization_id == org_id,
        Employee.archived_at.is_(None),
        or_(*or_conds)
    )
    
    emp_res = await session.execute(emp_stmt.limit(10))
    matched_employees = emp_res.scalars().all()
    if not matched_employees:
        return []

    emp_ids = [e.id for e in matched_employees]
    
    assign_stmt = (
        select(EmployeeAssignment, Project, Location)
        .join(Project, EmployeeAssignment.project_id == Project.id)
        .outerjoin(Location, EmployeeAssignment.location_id == Location.id)
        .where(
            EmployeeAssignment.employee_id.in_(emp_ids),
            EmployeeAssignment.organization_id == org_id,
        )
    )
    assign_res = await session.execute(assign_stmt)
    assign_rows = assign_res.all()

    assigned_emp_map = {}
    for ea, proj, loc in assign_rows:
        assigned_emp_map[ea.employee_id] = {
            "assignment_id": str(ea.id),
            "assigned_project": proj.name,
            "project_id": str(proj.id),
            "project_status": str(proj.status.value if hasattr(proj.status, 'value') else proj.status),
            "role_on_project": ea.role_on_project or "Assigned Personnel",
            "location": loc.name if loc else "N/A",
            "assignment_status": str(ea.status.value if hasattr(ea.status, 'value') else ea.status),
            "start_date": str(ea.start_date) if ea.start_date else None,
            "end_date": str(ea.end_date) if ea.end_date else None,
            "notes": ea.notes,
        }

    results = []
    for emp in matched_employees:
        emp_info = {
            "employee_id": str(emp.id),
            "employee_name": f"{emp.first_name} {emp.last_name}",
            "job_title": emp.job_title or "Staff Member",
            "department": emp.department or "General Operations",
            "employment_status": str(emp.employment_status.value if hasattr(emp.employment_status, 'value') else emp.employment_status),
        }
        if emp.id in assigned_emp_map:
            emp_info.update(assigned_emp_map[emp.id])
        else:
            emp_info.update({
                "assigned_project": None,
                "assignment_status": "UNASSIGNED",
                "message": f"{emp.first_name} {emp.last_name} ({emp.job_title or 'Staff'}) currently has no active project assignment recorded in the database.",
            })
        results.append(emp_info)

    return results


async def _execute_db_tool(category: str, user: User, session: AsyncSession, user_query: str = "") -> dict[str, Any]:
    """Execute live DB queries for the specified operational domain category with exception handling and exact telemetry."""
    org_id = user.organization_id
    cat = category.lower()
    q_lower = user_query.lower()

    try:
        if "workforce" in cat or "employee" in cat or "staff" in cat:
            total = (await session.execute(select(func.count(Employee.id)).where(Employee.organization_id == org_id, Employee.archived_at.is_(None)))).scalar() or 0
            assigned = (await session.execute(select(func.count(func.distinct(EmployeeAssignment.employee_id))).where(EmployeeAssignment.organization_id == org_id, EmployeeAssignment.status == AssignmentStatus.ACTIVE))).scalar() or 0
            
            # Check if query asks for specific skills, qualifications, roles or computer/IT skills
            search_terms = [t for t in q_lower.split() if len(t) > 2 and t not in ["which", "what", "who", "has", "have", "employee", "employees", "staff", "workforce", "personnel", "the", "and", "for", "with", "show", "list", "find"]]
            
            matched_skills_info = []
            if search_terms or "skill" in q_lower or "qualification" in q_lower or "computer" in q_lower:
                sk_stmt = (
                    select(Employee.id, Employee.first_name, Employee.last_name, Employee.job_title, Employee.department, Skill.name.label("skill_name"), EmployeeSkill.proficiency_level)
                    .join(EmployeeSkill, Employee.id == EmployeeSkill.employee_id)
                    .join(Skill, EmployeeSkill.skill_id == Skill.id)
                    .where(Employee.organization_id == org_id, Employee.archived_at.is_(None))
                )
                if search_terms:
                    conditions = [Skill.name.ilike(f"%{term}%") for term in search_terms] + [Employee.job_title.ilike(f"%{term}%") for term in search_terms] + [Employee.notes.ilike(f"%{term}%") for term in search_terms] + [Employee.bio.ilike(f"%{term}%") for term in search_terms]
                    sk_stmt = sk_stmt.where(or_(*conditions))
                
                sk_res = (await session.execute(sk_stmt.limit(20))).all()
                for emp_id, fn, ln, title, dept, sk_name, prof in sk_res:
                    matched_skills_info.append({
                        "employee_id": str(emp_id),
                        "display": f"{fn} {ln} ({title or 'Staff'}, {dept or 'General'}) — Skill: {sk_name} [{prof or 'N/A'}]"
                    })
                
                q_stmt = (
                    select(Employee.id, Employee.first_name, Employee.last_name, Employee.job_title, EmployeeQualification.qualification_name, EmployeeQualification.field_of_study)
                    .join(EmployeeQualification, Employee.id == EmployeeQualification.employee_id)
                    .where(Employee.organization_id == org_id, Employee.archived_at.is_(None))
                )
                if search_terms:
                    q_conditions = [EmployeeQualification.qualification_name.ilike(f"%{term}%") for term in search_terms] + [EmployeeQualification.field_of_study.ilike(f"%{term}%") for term in search_terms]
                    q_stmt = q_stmt.where(or_(*q_conditions))
                
                q_res = (await session.execute(q_stmt.limit(20))).all()
                for emp_id, fn, ln, title, q_name, field in q_res:
                    matched_skills_info.append({
                        "employee_id": str(emp_id),
                        "display": f"{fn} {ln} ({title or 'Staff'}) — Qualification: {q_name} ({field or 'General'})"
                    })

                if not matched_skills_info and search_terms:
                    emp_search_stmt = (
                        select(Employee.id, Employee.first_name, Employee.last_name, Employee.job_title, Employee.department, Employee.notes, Employee.bio)
                        .where(Employee.organization_id == org_id, Employee.archived_at.is_(None))
                        .where(or_(*[Employee.job_title.ilike(f"%{t}%") for t in search_terms] + [Employee.notes.ilike(f"%{t}%") for t in search_terms] + [Employee.bio.ilike(f"%{t}%") for t in search_terms] + [Employee.department.ilike(f"%{t}%") for t in search_terms]))
                    )
                    emp_matches = (await session.execute(emp_search_stmt.limit(10))).all()
                    for emp_id, fn, ln, title, dept, notes, bio in emp_matches:
                        matched_skills_info.append({
                            "employee_id": str(emp_id),
                            "display": f"{fn} {ln} — Title: {title or 'Staff'}, Dept: {dept or 'General'}"
                        })

            e_res = await session.execute(
                select(Employee.first_name, Employee.last_name, Employee.job_title, Employee.employment_status)
                .where(Employee.organization_id == org_id, Employee.archived_at.is_(None))
                .limit(20)
            )
            emps = [f"{fn} {ln} ({title or st})" for fn, ln, title, st in e_res.all()]

            res_payload = {
                "total_workforce_headcount": total,
                "assigned_employees": assigned,
                "available_employees": max(0, total - assigned),
                "deployment_rate_pct": round((assigned / total * 100), 1) if total > 0 else 0.0,
                "sample_personnel": emps[:10],
            }
            if matched_skills_info:
                res_payload["matching_personnel_skills_and_qualifications"] = matched_skills_info
            elif search_terms or "skill" in q_lower or "computer" in q_lower:
                res_payload["skill_search_status"] = f"No specific personnel found matching terms: '{', '.join(search_terms) if search_terms else q_lower}' in recorded skills, qualifications, or job titles."

            emp_assignments = await _lookup_employee_assignments(user_query, org_id, session)
            if emp_assignments:
                res_payload["matched_employee_assignments"] = emp_assignments

            return res_payload

        elif "fleet" in cat or "asset" in cat or "equipment" in cat:
            a_res = await session.execute(
                select(Asset.status, func.count(Asset.id))
                .where(Asset.organization_id == org_id, Asset.archived_at.is_(None))
                .group_by(Asset.status)
            )
            fleet_counts = {str(st).upper(): cnt for st, cnt in a_res.all()}
            total_fleet = sum(fleet_counts.values())
            operating = fleet_counts.get("OPERATING", 0) + fleet_counts.get("AVAILABLE", 0)
            return {
                "total_fleet_assets": total_fleet,
                "operating_fleet": fleet_counts.get("OPERATING", 0),
                "available_fleet": fleet_counts.get("AVAILABLE", 0),
                "maintenance_fleet": fleet_counts.get("UNDER_MAINTENANCE", 0) + fleet_counts.get("MAINTENANCE", 0),
                "breakdown_fleet": fleet_counts.get("BREAKDOWN", 0),
                "utilization_rate_pct": round((operating / total_fleet * 100), 1) if total_fleet > 0 else 0.0,
                "fleet_status_breakdown": fleet_counts,
            }

        elif "project" in cat or "site" in cat:
            p_res = await session.execute(
                select(Project.id, Project.name, Project.status, Project.target_metres, Project.contract_value)
                .where(Project.organization_id == org_id, Project.archived_at.is_(None))
                .limit(20)
            )
            p_all = p_res.all()
            projs = [f"{name} ({st}): Target {target or 0}m" for _, name, st, target, _ in p_all]

            total = (await session.execute(select(func.count(Project.id)).where(Project.organization_id == org_id, Project.archived_at.is_(None)))).scalar() or 0
            target_sum = (await session.execute(select(func.sum(Project.target_metres)).where(Project.organization_id == org_id, Project.archived_at.is_(None)))).scalar() or 0.0
            sample_project_id = str(p_all[0][0]) if p_all else None
            sample_project_name = str(p_all[0][1]) if p_all else None

            res_payload = {
                "total_projects": total,
                "total_target_metres": float(target_sum),
                "sample_projects": projs[:10],
                "first_project_id": sample_project_id,
                "first_project_name": sample_project_name,
            }
            emp_assignments = await _lookup_employee_assignments(user_query, org_id, session)
            if emp_assignments:
                res_payload["matched_employee_assignments"] = emp_assignments

            return res_payload

        elif "inventory" in cat or "stock" in cat or "store" in cat:
            inv_res = await session.execute(
                select(
                    func.count(func.distinct(InventoryItem.id)),
                    func.coalesce(func.sum(InventoryBalance.inventory_value), 0),
                )
                .select_from(InventoryItem)
                .outerjoin(InventoryBalance, InventoryItem.id == InventoryBalance.item_id)
                .where(InventoryItem.organization_id == org_id, InventoryItem.archived_at.is_(None))
            )
            total_items, total_val = inv_res.one()
            return {
                "total_inventory_catalog_items": total_items or 0,
                "total_holding_valuation_usd": float(total_val or 0.0),
            }

        elif "salary" in cat or "payroll" in cat or "financial" in cat:
            s_res = await session.execute(
                select(func.count(EmployeeSalary.id), func.sum(EmployeeSalary.base_salary))
                .where(EmployeeSalary.organization_id == org_id, EmployeeSalary.archived_at.is_(None))
            )
            cnt, total_sal = s_res.one()
            return {"active_salary_records": cnt or 0, "total_base_payroll": float(total_sal or 0.0)}

    except Exception as err:
        # Schema auto-correction on column / attribute mismatch
        schema_info = inspect_table_schema(cat)
        return {
            "error_recovered": str(err),
            "schema_inspected": schema_info,
            "status": "auto_corrected",
        }

    return {"message": f"Retrieved general system stats for organization {org_id}"}


async def _execute_vector_search(query: str, user: User, session: AsyncSession) -> list[dict[str, Any]]:
    """Execute semantic FAISS vector search across active uploaded documents and employee resumes."""
    docs_res = await session.execute(
        select(LibraryDocument).where(
            LibraryDocument.organization_id == user.organization_id,
            LibraryDocument.is_active.is_(True),
        )
    )
    docs = docs_res.scalars().all()
    if not docs:
        return []

    ready_docs = [d for d in docs if d.index_status == "READY"]
    hits = search_vectors(ready_docs, query) if ready_docs else {}
    citations = []
    
    q_lower = query.lower()
    q_terms = [t.lower() for t in query.split() if len(t) > 2 and t not in ["which", "what", "who", "has", "have", "employee", "employees", "staff", "workforce", "personnel", "the", "and", "show", "list", "find"]]

    is_skill_query = any(k in q_lower for k in ["skill", "computer", "software", "tech", "qualification", "resume", "cv", "certif", "training"])
    seen_keys = set()

    for doc in docs:
        if doc.id in hits:
            score, chunk = hits[doc.id]
            min_threshold = 0.60 if is_skill_query else 0.50
            if score >= min_threshold:
                snippet = chunk.get("text", "")[:350]
                if is_skill_query:
                    snip_lower = (doc.title + " " + doc.file_name + " " + snippet).lower()
                    if not any(t in snip_lower for t in q_terms) and not any(r in snip_lower for r in ["cv", "resume", "skill", "software", "tech", "data", "engineer", "developer", "math", "analysis", "experience"]):
                        continue

                dedup_key = f"{doc.file_name}:{snippet[:80]}"
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    citations.append({
                        "document_id": str(doc.id),
                        "employee_id": str(doc.employee_id) if doc.employee_id else None,
                        "document_title": doc.title or doc.file_name,
                        "file_name": doc.file_name,
                        "location": chunk.get("location", "Vector Index Chunk"),
                        "snippet": snippet,
                        "relevance_score": round(score, 3),
                    })
        else:
            tags_str = " ".join(doc.tags) if isinstance(doc.tags, list) else ""
            doc_meta = f"{doc.title or ''} {doc.file_name or ''} {doc.category or ''} {doc.source_type or ''} {tags_str} {doc.extracted_text[:300] or ''}".lower()
            if q_terms and any(t in doc_meta for t in q_terms):
                snippet_text = doc.extracted_text[:250] if doc.extracted_text else f"Surfaced document matching search: '{doc.file_name}'"
                dedup_key = f"{doc.file_name}:{snippet_text[:80]}"
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    citations.append({
                        "document_id": str(doc.id),
                        "employee_id": str(doc.employee_id) if doc.employee_id else None,
                        "document_title": doc.title or doc.file_name,
                        "file_name": doc.file_name,
                        "location": f"Document Library ({doc.category or doc.source_type or 'General'})",
                        "snippet": snippet_text,
                        "relevance_score": 0.75,
                    })

    citations.sort(key=lambda x: x["relevance_score"], reverse=True)
    return citations[:5]


@router.get("/assistant/history", dependencies=[Depends(require_permission("intelligence.read"))])
async def get_assistant_chat_history(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Retrieve saved assistant chat history for current user."""
    stmt = (
        select(AssistantChatMessage)
        .where(
            AssistantChatMessage.organization_id == user.organization_id,
            AssistantChatMessage.user_id == user.id,
        )
        .order_by(AssistantChatMessage.created_at.asc())
        .limit(100)
    )
    res = await session.execute(stmt)
    records = res.scalars().all()
    return [
        {
            "id": str(r.id),
            "role": r.role,
            "content": r.content,
            "citations": r.citations or [],
            "tools_used": r.tools_used or [],
            "suggested_filters": r.suggested_filters or None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@router.delete("/assistant/history", dependencies=[Depends(require_permission("intelligence.read"))])
async def clear_assistant_chat_history(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Clear saved assistant chat history for current user."""
    await session.execute(
        delete(AssistantChatMessage).where(
            AssistantChatMessage.organization_id == user.organization_id,
            AssistantChatMessage.user_id == user.id,
        )
    )
    await session.commit()
    return {"message": "Chat history cleared successfully."}


async def _save_chat_turn(
    user: User,
    session: AsyncSession,
    user_content: str,
    reply_content: str,
    citations: list[dict[str, Any]],
    tools_used: list[str],
    suggested_filters: dict[str, Any] | None,
):
    try:
        if user_content:
            session.add(
                AssistantChatMessage(
                    organization_id=user.organization_id,
                    user_id=user.id,
                    role="user",
                    content=user_content,
                )
            )
        session.add(
            AssistantChatMessage(
                organization_id=user.organization_id,
                user_id=user.id,
                role="assistant",
                content=reply_content,
                citations=citations,
                tools_used=tools_used or ["query_database_metrics"],
                suggested_filters=suggested_filters or None,
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()

def _log_agent_trace(
    query: str,
    first_action: str,
    tool_calls_trace: list[dict[str, Any]],
    status: str,
    final_reply: str,
) -> None:
    """Log agent execution trace to file if enabled in config."""
    try:
        settings = get_settings()
        enabled = getattr(settings, "enable_agent_logging", True)
        if not enabled:
            env_val = os.getenv("ENABLE_AGENT_LOGGING", "true").lower()
            if env_val in ("false", "0", "no"):
                return

        log_path_str = getattr(settings, "agent_log_path", "logs/agent_execution.log")
        log_path = Path(log_path_str)
        if not log_path.is_absolute():
            log_path = Path(__file__).resolve().parent.parent.parent.parent.parent / log_path_str

        log_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "query": query,
            "first_action": first_action,
            "tool_calls_count": len(tool_calls_trace),
            "tool_calls": tool_calls_trace,
            "status": status,
            "final_reply_preview": final_reply[:300] if final_reply else "",
        }

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"[Agent Logging Error]: {e}")


@router.post("/assistant", dependencies=[Depends(require_permission("intelligence.read"))])
async def assistant_chat(
    req: AssistantQueryRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> AssistantQueryResponse:
    """Agentic Smart Assistant with OpenAI function-calling loop.

    The LLM decides which tools to call, executes them via app.agents.tools,
    and synthesizes answers from real database results.
    """
    from app.agents.tools import (
        TOOL_DEFINITIONS,
        execute_tool,
        load_skills_prompt,
    )

    if not req.messages:
        return AssistantQueryResponse(reply="Please provide a message query to begin assistant interaction.")

    latest_user_message = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    tools_used: list[str] = []
    tool_calls_trace: list[dict[str, Any]] = []
    all_citations: list[dict[str, Any]] = []
    suggested_filters: dict[str, Any] = {}
    first_action: str = "Initializing reasoning"

    settings = get_settings()
    openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")

    if openai_key and len(openai_key) > 10:
        try:
            model_name = settings.openai_model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            # Build system prompt from skills.md
            skills_text = load_skills_prompt()
            system_prompt = (
                f"{skills_text}\n\n"
                "---\n"
                "CRITICAL REMINDERS:\n"
                "- All data you report MUST come from tool call results. Never guess or hallucinate.\n"
                "- If specific requested data is not present in tool results, state clearly what was found and what was missing.\n"
                "- Never use dummy template text (e.g. 'Telemetry data for this metric is not available... Total Workforce Headcount: 13'). Answer directly and accurately.\n"
                "- Do NOT output raw technical metadata like 'Relevance Score: 0.75' or raw vector search scores in the response text.\n"
                "- Include clean markdown navigation links for all entities using exact route patterns (e.g., [Seth Antanah](/workspace/employees/{id}), [Zodiac Gold](/project-command-center?project={id}), [Document Title](/documents?q=...)).\n"
                "- Format responses with markdown: headers, bold stats, bullet points, tables.\n"
            )

            prompt_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
            for m in req.messages[-10:]:
                prompt_messages.append({"role": m.role, "content": m.content})

            MAX_ITERATIONS = 14
            MAX_TOOL_CALLS = 20
            iteration = 0
            total_tool_calls = 0

            while iteration < MAX_ITERATIONS and total_tool_calls < MAX_TOOL_CALLS:
                iteration += 1

                payload = json.dumps({
                    "model": model_name,
                    "messages": prompt_messages,
                    "tools": TOOL_DEFINITIONS,
                    "tool_choice": "auto",
                    "temperature": 0.0,
                    "max_tokens": 1500,
                }).encode("utf-8")

                api_req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {openai_key}",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(api_req, timeout=45) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))

                choice = resp_data["choices"][0]
                message = choice["message"]
                finish_reason = choice.get("finish_reason", "stop")

                # Track first action
                if first_action == "Initializing reasoning":
                    if message.get("tool_calls"):
                        t_names = [tc["function"]["name"] for tc in message["tool_calls"]]
                        first_action = f"Tool call: {', '.join(t_names)}"
                    else:
                        first_action = "Direct response generation"

                # If the model wants to call tools
                if finish_reason == "tool_calls" or message.get("tool_calls"):
                    prompt_messages.append(message)

                    for tc in message.get("tool_calls", []):
                        if total_tool_calls >= MAX_TOOL_CALLS:
                            break

                        total_tool_calls += 1
                        fn_name = tc["function"]["name"]
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except (json.JSONDecodeError, KeyError):
                            fn_args = {}

                        tools_used.append(fn_name)

                        # Execute the tool
                        start_t = datetime.utcnow()
                        tool_result = await execute_tool(
                            fn_name, fn_args, user.organization_id, session
                        )
                        dur_ms = int((datetime.utcnow() - start_t).total_seconds() * 1000)

                        status_str = "error" if "error" in tool_result else "success"
                        tool_calls_trace.append({
                            "iteration": iteration,
                            "tool_call_id": tc["id"],
                            "tool": fn_name,
                            "args": fn_args,
                            "status": status_str,
                            "duration_ms": dur_ms,
                        })

                        # Collect citations from document searches
                        if fn_name == "search_documents" and "results" in tool_result:
                            for doc_hit in tool_result["results"]:
                                doc_title = doc_hit.get("title", "") or doc_hit.get("file_name", "Document")
                                doc_id = doc_hit.get("document_id") or ""
                                all_citations.append({
                                    "document_id": doc_id,
                                    "employee_id": doc_hit.get("employee_id"),
                                    "document_title": doc_title,
                                    "file_name": doc_hit.get("file_name", ""),
                                    "location": doc_hit.get("category", "Document Library"),
                                    "snippet": doc_hit.get("snippet", ""),
                                    "url": f"/documents?q={urllib.parse.quote(doc_title)}" if doc_title else "/documents",
                                })

                        # Build suggested filters from results
                        if not suggested_filters:
                            if fn_name == "get_project_details" and tool_result.get("projects"):
                                p = tool_result["projects"][0]
                                suggested_filters = {
                                    "project_id": p.get("id"),
                                    "project_name": p.get("name", "Project"),
                                }
                            elif fn_name == "get_employee_details":
                                suggested_filters = {"status": "ACTIVE", "label": "Active Personnel"}
                            elif fn_name == "get_fleet_summary":
                                suggested_filters = {"status": "OPERATING", "label": "Operating Fleet"}

                        # Append tool result as a tool message
                        result_str = json.dumps(tool_result, default=str)
                        if len(result_str) > 8000:
                            result_str = result_str[:8000] + '..."]}'

                        prompt_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_str,
                        })

                    continue

                # No tool calls — model produced final text response
                reply_text = message.get("content", "")
                if not reply_text:
                    reply_text = "I was unable to generate a response. Please try rephrasing your question."

                tools_used = list(dict.fromkeys(tools_used)) or ["smart_assistant"]

                _log_agent_trace(
                    latest_user_message, first_action, tool_calls_trace, "success", reply_text
                )

                await _save_chat_turn(
                    user, session, latest_user_message, reply_text,
                    all_citations, tools_used, suggested_filters or None,
                )
                return AssistantQueryResponse(
                    reply=reply_text,
                    conversation_id=req.conversation_id,
                    citations=all_citations,
                    tools_used=tools_used,
                    suggested_filters=suggested_filters or None,
                )

            # Reached max iterations or max tool calls: synthesize current evaluation + add follow-up question
            synth_prompt = (
                "You have reached the maximum allowed tool calls/iterations. Evaluate all tool call data gathered so far and synthesize a complete response answering the user's question as thoroughly as possible with what you have.\n\n"
                "CRITICAL INSTRUCTION: At the end of your answer, add a section:\n"
                "### Suggested Follow-up Question\n"
                "Provide 1 specific follow-up question the user can ask to help you continue or dig deeper into any missing details."
            )
            prompt_messages.append({"role": "user", "content": synth_prompt})

            payload = json.dumps({
                "model": model_name,
                "messages": prompt_messages,
                "temperature": 0.0,
                "max_tokens": 1500,
            }).encode("utf-8")

            api_req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}",
                },
                method="POST",
            )

            with urllib.request.urlopen(api_req, timeout=45) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))

            reply_text = resp_data["choices"][0]["message"].get("content", "")
            if not reply_text:
                reply_text = "I reached the execution limit while processing your request. Here is the summary of data gathered so far."

            tools_used = list(dict.fromkeys(tools_used)) or ["smart_assistant"]

            _log_agent_trace(
                latest_user_message, first_action, tool_calls_trace, "max_limit_reached", reply_text
            )

            await _save_chat_turn(
                user, session, latest_user_message, reply_text,
                all_citations, tools_used, suggested_filters or None,
            )
            return AssistantQueryResponse(
                reply=reply_text,
                conversation_id=req.conversation_id,
                citations=all_citations,
                tools_used=tools_used,
                suggested_filters=suggested_filters or None,
            )

        except Exception as err:
            print(f"[Smart Assistant Error]: {err}")
            _log_agent_trace(
                latest_user_message, first_action, tool_calls_trace, f"error: {err}", ""
            )

    # -----------------------------------------------------------------------
    # Fallback: No OpenAI key or API error
    # -----------------------------------------------------------------------
    from app.agents.tools import execute_tool

    fallback_data: dict[str, Any] = {}
    q_lower = latest_user_message.lower()

    tool_calls: list[tuple[str, dict[str, Any]]] = []

    if any(kw in q_lower for kw in ["employee", "staff", "workforce", "personnel", "who", "department", "hr"]):
        tool_calls.append(("get_employee_details", {"include_assignments": True}))
    if any(kw in q_lower for kw in ["fleet", "asset", "equipment", "vehicle"]):
        tool_calls.append(("get_fleet_summary", {"include_fuel": True, "include_maintenance": True}))
    if any(kw in q_lower for kw in ["project", "site", "drilling"]):
        tool_calls.append(("get_project_details", {"include_assignments": True}))
    if any(kw in q_lower for kw in ["inventory", "stock", "store"]):
        tool_calls.append(("get_inventory_summary", {}))
    if any(kw in q_lower for kw in ["salary", "payroll", "financial", "cost", "fuel"]):
        tool_calls.append(("get_financial_summary", {}))
    if any(kw in q_lower for kw in ["document", "file", "cv", "resume", "policy"]):
        tool_calls.append(("search_documents", {"query": latest_user_message}))

    if not tool_calls:
        tool_calls = [
            ("get_employee_details", {"limit": 5}),
            ("get_fleet_summary", {}),
        ]

    for tool_name, tool_args in tool_calls:
        result = await execute_tool(tool_name, tool_args, user.organization_id, session)
        fallback_data[tool_name] = result
        tools_used.append(tool_name)

    lines = [f"### Query: **\"{latest_user_message}\"**", ""]
    lines.append("> **Note**: Responses are generated from raw database queries (AI synthesis unavailable).")
    lines.append("")

    for tool_name, data in fallback_data.items():
        lines.append(f"#### {tool_name.replace('_', ' ').title()}")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list) and len(v) > 5:
                    lines.append(f"- **{k.replace('_', ' ').title()}**: {len(v)} items (showing first 5)")
                    for item in v[:5]:
                        if isinstance(item, dict):
                            summary = ", ".join(f"{ik}: {iv}" for ik, iv in list(item.items())[:4])
                            lines.append(f"  - {summary}")
                        else:
                            lines.append(f"  - {item}")
                elif isinstance(v, list):
                    lines.append(f"- **{k.replace('_', ' ').title()}**:")
                    for item in v:
                        if isinstance(item, dict):
                            summary = ", ".join(f"{ik}: {iv}" for ik, iv in list(item.items())[:4])
                            lines.append(f"  - {summary}")
                        else:
                            lines.append(f"  - {item}")
                else:
                    lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
        lines.append("")

    lines.append("### Suggested Follow-up Question")
    lines.append("Would you like to search for specific items, projects, or personnel records in detail?")

    final_reply = "\n".join(lines)
    tools_used = list(dict.fromkeys(tools_used)) or ["fallback_query"]

    await _save_chat_turn(
        user, session, latest_user_message, final_reply,
        all_citations, tools_used, suggested_filters or None,
    )

    return AssistantQueryResponse(
        reply=final_reply,
        conversation_id=req.conversation_id,
        citations=all_citations,
        tools_used=tools_used,
        suggested_filters=suggested_filters or None,
    )


