"""Create, list and update project action tracker entries."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import Asset, Employee, Project, User
from app.models.operational_logs import ActionTracker
from app.schemas.action_tracker import ActionTrackerCreate, ActionTrackerRead, ActionTrackerUpdate

router = APIRouter(prefix="/action-tracker", tags=["Action tracker"])


async def validate_links(session: AsyncSession, actor: User, values: dict) -> None:
    checks = ((Project, "project_id", "Project"), (Asset, "asset_id", "Equipment"), (Employee, "responsible_employee_id", "Responsible employee"))
    for model, key, label in checks:
        value = values.get(key)
        if value and not await session.scalar(select(model.id).where(
            model.id == value, model.organization_id == actor.organization_id, model.archived_at.is_(None),
        )):
            raise HTTPException(404, f"Selected {label.lower()} was not found")


@router.get("", response_model=list[ActionTrackerRead])
async def list_actions(project_id: uuid.UUID | None = Query(None), actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    query = select(ActionTracker).where(ActionTracker.organization_id == actor.organization_id, ActionTracker.archived_at.is_(None))
    if project_id:
        query = query.where(ActionTracker.project_id == project_id)
    return list((await session.scalars(query.order_by(ActionTracker.action_date.desc(), ActionTracker.created_at.desc()))).all())


@router.post("", response_model=ActionTrackerRead, status_code=201)
async def create_action(body: ActionTrackerCreate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    data = body.model_dump()
    await validate_links(session, actor, data)
    row = ActionTracker(organization_id=actor.organization_id, created_by_id=actor.id, updated_by_id=actor.id, **data)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/{action_id}", response_model=ActionTrackerRead)
async def update_action(action_id: uuid.UUID, body: ActionTrackerUpdate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    row = await session.scalar(select(ActionTracker).where(ActionTracker.id == action_id, ActionTracker.organization_id == actor.organization_id, ActionTracker.archived_at.is_(None)))
    if not row:
        raise HTTPException(404, "Action tracker entry not found")
    changes = body.model_dump(exclude_unset=True)
    await validate_links(session, actor, {key: changes.get(key, getattr(row, key)) for key in ("project_id", "asset_id", "responsible_employee_id")})
    action_date = changes.get("action_date", row.action_date)
    completion_date = changes.get("completion_date", row.completion_date)
    if completion_date and completion_date < action_date:
        raise HTTPException(422, "Completion date must be on or after the action date")
    if changes.get("priority"):
        changes["priority"] = changes["priority"].upper()
    if changes.get("status"):
        changes["status"] = changes["status"].upper().replace(" ", "_")
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_id = actor.id
    await session.commit()
    await session.refresh(row)
    return row
