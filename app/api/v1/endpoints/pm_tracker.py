"""Preventive maintenance tracker API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import Asset, Employee, Project, User
from app.models.operational_logs import PMTracker
from app.schemas.pm_tracker import PMTrackerCreate, PMTrackerRead, PMTrackerUpdate

router = APIRouter(prefix="/pm-tracker", tags=["PM tracker"])


async def validate_links(session: AsyncSession, actor: User, data: dict) -> None:
    for model, key, label in ((Project, "project_id", "Project"), (Asset, "asset_id", "Equipment"), (Employee, "technician_employee_id", "Technician")):
        value = data.get(key)
        if value and not await session.scalar(select(model.id).where(model.id == value, model.organization_id == actor.organization_id, model.archived_at.is_(None))):
            raise HTTPException(404, f"Selected {label.lower()} was not found")


@router.get("", response_model=list[PMTrackerRead])
async def list_pm_tracker(project_id: uuid.UUID | None = Query(None), actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    query = select(PMTracker).where(PMTracker.organization_id == actor.organization_id, PMTracker.archived_at.is_(None))
    if project_id:
        query = query.where(PMTracker.project_id == project_id)
    return list((await session.scalars(query.order_by(PMTracker.due_date.asc(), PMTracker.created_at.desc()))).all())


@router.post("", response_model=PMTrackerRead, status_code=201)
async def create_pm_tracker(body: PMTrackerCreate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    data = body.model_dump()
    await validate_links(session, actor, data)
    row = PMTracker(organization_id=actor.organization_id, created_by_id=actor.id, updated_by_id=actor.id, **data)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/{record_id}", response_model=PMTrackerRead)
async def update_pm_tracker(record_id: uuid.UUID, body: PMTrackerUpdate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    row = await session.scalar(select(PMTracker).where(PMTracker.id == record_id, PMTracker.organization_id == actor.organization_id, PMTracker.archived_at.is_(None)))
    if not row:
        raise HTTPException(404, "PM tracker entry not found")
    changes = body.model_dump(exclude_unset=True)
    await validate_links(session, actor, {key: changes.get(key, getattr(row, key)) for key in ("project_id", "asset_id", "technician_employee_id")})
    if changes.get("planned_actual") is not None:
        changes["planned_actual"] = changes["planned_actual"].upper()
        if changes["planned_actual"] not in {"PLANNED", "ACTUAL"}:
            raise HTTPException(422, "Choose Planned or Actual")
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_id = actor.id
    await session.commit()
    await session.refresh(row)
    return row
