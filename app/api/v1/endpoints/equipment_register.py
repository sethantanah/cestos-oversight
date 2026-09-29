"""Project equipment register API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import Asset, Project, User
from app.models.operational_logs import EquipmentRegister
from app.schemas.equipment_register import EquipmentRegisterCreate, EquipmentRegisterRead, EquipmentRegisterUpdate

router = APIRouter(prefix="/equipment-register", tags=["Equipment register"])


async def validate_links(session: AsyncSession, actor: User, data: dict) -> None:
    for model, key, label in ((Project, "project_id", "Project"), (Asset, "asset_id", "Equipment")):
        value = data.get(key)
        if value and not await session.scalar(select(model.id).where(model.id == value, model.organization_id == actor.organization_id, model.archived_at.is_(None))):
            raise HTTPException(404, f"Selected {label.lower()} was not found")


@router.get("", response_model=list[EquipmentRegisterRead])
async def list_register(project_id: uuid.UUID | None = Query(None), actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    query = select(EquipmentRegister).where(EquipmentRegister.organization_id == actor.organization_id, EquipmentRegister.archived_at.is_(None))
    if project_id:
        query = query.where(EquipmentRegister.project_id == project_id)
    return list((await session.scalars(query.order_by(EquipmentRegister.equipment.asc(), EquipmentRegister.created_at.desc()))).all())


@router.post("", response_model=EquipmentRegisterRead, status_code=201)
async def create_register(body: EquipmentRegisterCreate, response: Response, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    data = body.model_dump()
    await validate_links(session, actor, data)
    equipment_key = func.lower(func.trim(EquipmentRegister.equipment)) == data["equipment"].strip().lower()
    unit_number = (data.get("unit_number") or "").strip().lower()
    unit_key = func.lower(func.trim(func.coalesce(EquipmentRegister.unit_number, ""))) == unit_number
    project_key = EquipmentRegister.project_id == data.get("project_id") if data.get("project_id") else EquipmentRegister.project_id.is_(None)
    existing = await session.scalar(
        select(EquipmentRegister)
        .where(
            EquipmentRegister.organization_id == actor.organization_id,
            EquipmentRegister.archived_at.is_(None),
            cast(EquipmentRegister.created_at, Date) == func.current_date(),
            equipment_key,
            unit_key,
            project_key,
        )
        .order_by(EquipmentRegister.created_at.desc())
        .with_for_update()
    )
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        existing.updated_by_id = actor.id
        response.status_code = 200
        await session.commit()
        await session.refresh(existing)
        return existing

    row = EquipmentRegister(organization_id=actor.organization_id, created_by_id=actor.id, updated_by_id=actor.id, **data)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/{record_id}", response_model=EquipmentRegisterRead)
async def update_register(record_id: uuid.UUID, body: EquipmentRegisterUpdate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    row = await session.scalar(select(EquipmentRegister).where(EquipmentRegister.id == record_id, EquipmentRegister.organization_id == actor.organization_id, EquipmentRegister.archived_at.is_(None)))
    if not row:
        raise HTTPException(404, "Equipment register entry not found")
    changes = body.model_dump(exclude_unset=True)
    await validate_links(session, actor, {key: changes.get(key, getattr(row, key)) for key in ("project_id", "asset_id")})
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_id = actor.id
    await session.commit()
    await session.refresh(row)
    return row
