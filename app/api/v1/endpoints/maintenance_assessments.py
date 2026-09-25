"""Create and manage structured fleet maintenance assessments."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import Asset, Employee, Location, Project, User
from app.models.operational_logs import MaintenanceAssessmentReport
from app.schemas.maintenance_assessments import (
    MaintenanceAssessmentCreate,
    MaintenanceAssessmentRead,
    MaintenanceAssessmentUpdate,
)

router = APIRouter(prefix="/maintenance-assessments", tags=["Maintenance assessments"])


async def validate_links(session: AsyncSession, actor: User, data: dict) -> None:
    project_id = data.get("project_id")
    site_id = data.get("site_location_id")
    if project_id and not await session.scalar(select(Project.id).where(
        Project.id == project_id,
        Project.organization_id == actor.organization_id,
        Project.archived_at.is_(None),
    )):
        raise HTTPException(404, "Selected project not found")
    if site_id:
        site = await session.scalar(select(Location).where(
            Location.id == site_id,
            Location.organization_id == actor.organization_id,
            Location.archived_at.is_(None),
        ))
        if not site:
            raise HTTPException(404, "Selected project site not found")
        if project_id and site.project_id != project_id:
            raise HTTPException(422, "Selected site does not belong to this project")
    employee_id = data.get("prepared_by_employee_id")
    if employee_id and not await session.scalar(select(Employee.id).where(
        Employee.id == employee_id,
        Employee.organization_id == actor.organization_id,
        Employee.archived_at.is_(None),
    )):
        raise HTTPException(404, "Selected report preparer was not found")
    asset_ids = data.get("equipment_asset_ids")
    if asset_ids is not None:
        normalized = {uuid.UUID(str(asset_id)) for asset_id in asset_ids}
        if normalized:
            found = set((await session.scalars(select(Asset.id).where(
                Asset.id.in_(normalized),
                Asset.organization_id == actor.organization_id,
                Asset.archived_at.is_(None),
            ))).all())
            if found != normalized:
                raise HTTPException(404, "One or more selected equipment records were not found")


def prepare_json(data: dict) -> dict:
    if "equipment_asset_ids" in data and data["equipment_asset_ids"] is not None:
        data["equipment_asset_ids"] = [str(value) for value in data["equipment_asset_ids"]]
    return data


@router.get("", response_model=list[MaintenanceAssessmentRead])
async def list_reports(
    project_id: uuid.UUID | None = Query(None),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(MaintenanceAssessmentReport).where(
        MaintenanceAssessmentReport.organization_id == actor.organization_id,
        MaintenanceAssessmentReport.archived_at.is_(None),
    )
    if project_id:
        stmt = stmt.where(MaintenanceAssessmentReport.project_id == project_id)
    return list((await session.scalars(stmt.order_by(
        MaintenanceAssessmentReport.report_date.desc(),
        MaintenanceAssessmentReport.created_at.desc(),
    ))).all())


@router.post("", response_model=MaintenanceAssessmentRead, status_code=201)
async def create_report(
    body: MaintenanceAssessmentCreate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    data = prepare_json(body.model_dump())
    await validate_links(session, actor, data)
    report_number = (data.pop("report_number") or f"MA-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}").strip()
    duplicate = await session.scalar(select(MaintenanceAssessmentReport.id).where(
        MaintenanceAssessmentReport.organization_id == actor.organization_id,
        MaintenanceAssessmentReport.report_number == report_number,
    ).limit(1))
    if duplicate:
        raise HTTPException(409, "That assessment report number is already in use")
    row = MaintenanceAssessmentReport(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        updated_by_id=actor.id,
        report_number=report_number,
        **data,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Assessment report number is already in use") from exc
    await session.refresh(row)
    return row


@router.get("/{report_id}", response_model=MaintenanceAssessmentRead)
async def get_report(
    report_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(select(MaintenanceAssessmentReport).where(
        MaintenanceAssessmentReport.id == report_id,
        MaintenanceAssessmentReport.organization_id == actor.organization_id,
        MaintenanceAssessmentReport.archived_at.is_(None),
    ))
    if not row:
        raise HTTPException(404, "Maintenance assessment report not found")
    return row


@router.patch("/{report_id}", response_model=MaintenanceAssessmentRead)
async def update_report(
    report_id: uuid.UUID,
    body: MaintenanceAssessmentUpdate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(select(MaintenanceAssessmentReport).where(
        MaintenanceAssessmentReport.id == report_id,
        MaintenanceAssessmentReport.organization_id == actor.organization_id,
        MaintenanceAssessmentReport.archived_at.is_(None),
    ))
    if not row:
        raise HTTPException(404, "Maintenance assessment report not found")
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at < datetime.now(timezone.utc) - timedelta(days=10):
        raise HTTPException(409, "Assessment reports can only be edited within 10 days of creation")
    changes = prepare_json(body.model_dump(exclude_unset=True))
    if changes.get("report_number") is None:
        changes.pop("report_number", None)
    combined = {key: changes.get(key, getattr(row, key)) for key in (
        "project_id", "site_location_id", "prepared_by_employee_id", "equipment_asset_ids"
    )}
    await validate_links(session, actor, combined)
    period_start = changes.get("reporting_period_start", row.reporting_period_start)
    period_end = changes.get("reporting_period_end", row.reporting_period_end)
    if period_end < period_start:
        raise HTTPException(422, "Reporting period end must be on or after its start")
    new_number = changes.get("report_number")
    if new_number and new_number != row.report_number:
        duplicate = await session.scalar(select(MaintenanceAssessmentReport.id).where(
            MaintenanceAssessmentReport.organization_id == actor.organization_id,
            MaintenanceAssessmentReport.report_number == new_number,
            MaintenanceAssessmentReport.id != row.id,
        ).limit(1))
        if duplicate:
            raise HTTPException(409, "That assessment report number is already in use")
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_id = actor.id
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Assessment report number is already in use") from exc
    await session.refresh(row)
    return row
