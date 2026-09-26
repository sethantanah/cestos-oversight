"""Administrative record lookup and safe archive preview for Command Center."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect
from fastapi.encoders import jsonable_encoder

from app.core.dependencies import get_current_active_user, scoped_roles
from app.db.base import Base
from app.db.session import get_session
from app.models import Asset, Employee, Project, User
from app.models.inventory import Supplier

router = APIRouter(prefix="/command-center", tags=["Command Center"])
RECORDS: dict[str, type] = {
    "projects": Project,
    "employees": Employee,
    "equipment": Asset,
    "suppliers": Supplier,
}


class ArchiveRequest(BaseModel):
    expected_updated_at: datetime


def require_admin(actor: User) -> None:
    if actor.is_superuser:
        return
    permissions = {
        permission.code
        for role in scoped_roles(actor)
        if role.is_system_role and role.organization_id is None or role.organization_id == actor.organization_id
        for permission in role.permissions
    }
    if "admin.manage" not in permissions:
        raise HTTPException(status_code=403, detail="Administrator permission is required")


def record_label(row: Any) -> str:
    for name in ("name", "full_name", "title", "project_number", "employee_number", "asset_number", "supplier_name", "email"):
        value = getattr(row, name, None)
        if value:
            return str(value)
    return str(getattr(row, "id", "Record"))


def record_data(row: Any) -> dict[str, Any]:
    return jsonable_encoder({column.key: getattr(row, column.key, None) for column in inspect(row).mapper.column_attrs})


async def get_record(session: AsyncSession, actor: User, entity: str, record_id: uuid.UUID):
    model = RECORDS.get(entity)
    if model is None:
        raise HTTPException(status_code=404, detail="Unsupported record type")
    stmt = select(model).where(model.id == record_id, model.organization_id == actor.organization_id)
    if hasattr(model, "archived_at"):
        stmt = stmt.where(model.archived_at.is_(None))
    row = await session.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return row


async def impact_for(session: AsyncSession, actor: User, model: type, record_id: uuid.UUID) -> list[dict[str, Any]]:
    impact: list[dict[str, Any]] = []
    for mapper in Base.registry.mappers:
        child_model = mapper.class_
        if child_model is model or not hasattr(child_model, "__table__"):
            continue
        foreign_key_columns = []
        for column in child_model.__table__.columns:
            if any(fk.column.table.name == model.__tablename__ for fk in column.foreign_keys):
                foreign_key_columns.append(getattr(child_model, column.key))
        if not foreign_key_columns:
            continue
        conditions = [column == record_id for column in foreign_key_columns]
        filters = [or_(*conditions)]
        if hasattr(child_model, "organization_id"):
            filters.append(child_model.organization_id == actor.organization_id)
        if hasattr(child_model, "archived_at"):
            filters.append(child_model.archived_at.is_(None))
        count = int((await session.scalar(select(func.count()).select_from(child_model).where(*filters))) or 0)
        if not count:
            continue
        rows = list((await session.scalars(select(child_model).where(*filters).limit(500))).all())
        impact.append({
            "entity": child_model.__tablename__,
            "label": child_model.__name__,
            "count": count,
            "truncated": count > len(rows),
            "items": [{"id": str(row.id), "label": record_label(row)} for row in rows],
        })
    return sorted(impact, key=lambda item: item["label"].lower())


@router.get("/records/{entity}")
async def list_records(
    entity: str,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    require_admin(actor)
    model = RECORDS.get(entity)
    if model is None:
        raise HTTPException(status_code=404, detail="Unsupported record type")
    stmt = select(model).where(model.organization_id == actor.organization_id)
    if hasattr(model, "archived_at"):
        stmt = stmt.where(model.archived_at.is_(None))
    if hasattr(model, "is_active"):
        stmt = stmt.where(model.is_active.is_(True))
    rows = list((await session.scalars(stmt.order_by(model.created_at.desc()).limit(1000))).all())
    return {"items": [record_data(row) for row in rows], "count": len(rows), "truncated": len(rows) == 1000}


@router.get("/records/{entity}/{record_id}/impact")
async def preview_archive(
    entity: str,
    record_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    require_admin(actor)
    row = await get_record(session, actor, entity, record_id)
    return {"record": record_data(row), "label": record_label(row), "dependencies": await impact_for(session, actor, RECORDS[entity], record_id)}


@router.post("/records/{entity}/{record_id}/archive")
async def archive_record(
    entity: str,
    record_id: uuid.UUID,
    body: ArchiveRequest,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    require_admin(actor)
    row = await get_record(session, actor, entity, record_id)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(status_code=409, detail="This record changed after the preview. Refresh the preview before archiving.")
    dependencies = await impact_for(session, actor, RECORDS[entity], record_id)
    label = record_label(row)
    if entity == "projects":
        row.archived_at = datetime.now(timezone.utc)
        row.is_active = False
        row.updated_by_id = actor.id
        row.updated_at = datetime.now(timezone.utc)
        from app.services.audit import record_audit
        record_audit(
            session,
            organization_id=actor.organization_id,
            actor_user_id=actor.id,
            action="project.archived",
            entity_type="project",
            entity_id=row.id,
            new_values={"project_number": row.project_number, "name": row.name},
            metadata={"source": "command_center"},
        )
        await session.commit()
    elif entity == "employees":
        from app.services.employees import EmployeeService
        await EmployeeService(session, actor).archive(record_id)
    elif entity == "equipment":
        from app.services.assets import AssetService
        await AssetService(session, actor).archive(record_id)
    else:
        from app.services.inventory import InventoryService
        await InventoryService(session, actor).archive("suppliers", record_id)
    return {"archived": True, "record": label, "dependencies_preserved": dependencies}
