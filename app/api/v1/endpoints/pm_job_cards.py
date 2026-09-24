import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import User, Asset, Location
from app.models.maintenance_hse import MaintenanceWorkOrder
from app.models.operational_logs import PMTemplate, PMJobCard
from app.schemas.pm_job_cards import PMTemplateCreate, PMTemplateRead, PMJobCardCreate, PMJobCardUpdate, PMJobCardRead
from app.models.operational_logs import BreakdownJobCard
from app.schemas.breakdown_job_cards import BreakdownJobCardCreate, BreakdownJobCardRead, BreakdownJobCardUpdate

router = APIRouter(prefix="/pm-job-cards", tags=["PM job cards"])

@router.get("/breakdown", response_model=list[BreakdownJobCardRead])
async def list_breakdown(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(BreakdownJobCard).where(BreakdownJobCard.organization_id == actor.organization_id, BreakdownJobCard.archived_at.is_(None)).order_by(BreakdownJobCard.created_at.desc()))).all())

@router.post("/breakdown", response_model=BreakdownJobCardRead, status_code=201)
async def create_breakdown(body: BreakdownJobCardCreate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    asset = await session.scalar(select(Asset).where(Asset.id == body.asset_id, Asset.organization_id == actor.organization_id))
    if not asset: raise HTTPException(404, "Equipment not found")
    if body.site_location_id:
        site = await session.scalar(select(Location).where(Location.id == body.site_location_id, Location.organization_id == actor.organization_id))
        if not site:
            raise HTTPException(404, "Selected project site not found")
        if body.project_id and site.project_id != body.project_id:
            raise HTTPException(422, "Selected site does not belong to this project")
    row = BreakdownJobCard(organization_id=actor.organization_id, created_by_id=actor.id, job_card_number=f"BR-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}", **body.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "The breakdown job card could not be saved because one of its linked records changed. Refresh the form and try again.") from exc
    await session.refresh(row)
    return row


@router.patch("/breakdown/{card_id}", response_model=BreakdownJobCardRead)
async def update_breakdown(
    card_id: uuid.UUID,
    body: BreakdownJobCardUpdate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(select(BreakdownJobCard).where(
        BreakdownJobCard.id == card_id,
        BreakdownJobCard.organization_id == actor.organization_id,
        BreakdownJobCard.archived_at.is_(None),
    ))
    if not row:
        raise HTTPException(404, "Breakdown job card not found")
    if row.created_at < datetime.now(timezone.utc) - timedelta(days=10):
        raise HTTPException(409, "Job cards can only be edited within 10 days of creation")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("site_location_id"):
        site = await session.scalar(select(Location).where(Location.id == changes["site_location_id"], Location.organization_id == actor.organization_id))
        if not site:
            raise HTTPException(404, "Selected project site not found")
        if row.project_id and site.project_id != row.project_id:
            raise HTTPException(422, "Selected site does not belong to this project")
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_id = actor.id
    await session.commit()
    await session.refresh(row)
    return row
DEFAULT_INSPECTION = [
    {"sequence": i + 1, "system_component": system, "service_tasks": tasks, "condition": None, "action_taken": "", "parts_used": [], "remarks": ""}
    for i, (system, tasks) in enumerate([
        ("ENGINE", ["Oil level, leaks, filters", "V-belt, mounts"]), ("COOLING SYSTEM", ["Coolant, radiator cap", "Hoses / fan blades"]), ("FUEL SYSTEM", ["Filters / water", "Separator / fuel cap"]), ("HYDRAULIC SYSTEM", ["Oil level, hoses, fittings, leaks"]), ("ELECTRICAL SYSTEM", ["Batteries / terminals, charging, starter motor, lights"]), ("DRILLING SYSTEM", ["Feed, rotation winch, cylinders, controls"]), ("ROTATION HEAD", ["Lub oil level, chuck bolts, oil filter"]), ("CHASSIS / STRUCTURE", ["Bolts, cracks, pins, bushes, mounting points"]), ("SAFETY SYSTEM", ["E-stops, alarms, guards, fire equipment"]), ("LUBRICATION", ["Grease rotation head, wire / winch sheaves"]), ("UNDERCARRIAGE", ["Oil / idler, sprocket / wheel, track chain, roller"]), ("FUNCTION TEST", ["Run machine and verify operation"])
    ])
]

@router.get("/templates", response_model=list[PMTemplateRead])
async def templates(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(PMTemplate).where(PMTemplate.organization_id == actor.organization_id, PMTemplate.is_active.is_(True)).order_by(PMTemplate.name))).all())

@router.post("/templates", response_model=PMTemplateRead, status_code=201)
async def create_template(body: PMTemplateCreate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    row = PMTemplate(organization_id=actor.organization_id, created_by_id=actor.id, **body.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "That PM Job Card No. is already in use. Choose another number or generate one.") from exc
    await session.refresh(row)
    return row

@router.get("", response_model=list[PMJobCardRead])
async def list_cards(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(PMJobCard).where(PMJobCard.organization_id == actor.organization_id, PMJobCard.archived_at.is_(None)).order_by(PMJobCard.created_at.desc()))).all())

@router.post("", response_model=PMJobCardRead, status_code=201)
async def create_card(body: PMJobCardCreate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    if body.asset_id:
        asset = await session.scalar(select(Asset).where(Asset.id == body.asset_id, Asset.organization_id == actor.organization_id))
        if not asset:
            raise HTTPException(404, "Equipment not found")
    elif not str(body.pm_control.get("equipment", "")).strip():
        raise HTTPException(422, "Enter an equipment name or select equipment from this project.")
    if body.work_order_id:
        if not body.asset_id:
            raise HTTPException(422, "A saved work order can only be linked to selected registered equipment.")
        work_order = await session.scalar(select(MaintenanceWorkOrder).where(MaintenanceWorkOrder.id == body.work_order_id, MaintenanceWorkOrder.organization_id == actor.organization_id, MaintenanceWorkOrder.asset_id == body.asset_id))
        if not work_order: raise HTTPException(404, "Work order not found for this equipment")
    template = await session.scalar(select(PMTemplate).where(PMTemplate.id == body.template_id, PMTemplate.organization_id == actor.organization_id)) if body.template_id else None
    number = (body.job_card_number or f"PM-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}").strip()
    duplicate = await session.scalar(select(PMJobCard.id).where(PMJobCard.job_card_number == number).limit(1))
    if duplicate:
        raise HTTPException(409, "That PM Job Card No. is already in use. Choose another number or generate one.")
    row = PMJobCard(organization_id=actor.organization_id, created_by_id=actor.id, job_card_number=number, inspection_items=body.inspection_items if body.inspection_items is not None else (template.inspection_items if template else DEFAULT_INSPECTION), **body.model_dump(exclude={"inspection_items", "job_card_number"}))
    session.add(row); await session.commit(); await session.refresh(row); return row

@router.get("/{card_id}", response_model=PMJobCardRead)
async def get_card(card_id: uuid.UUID, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    row = await session.scalar(select(PMJobCard).where(PMJobCard.id == card_id, PMJobCard.organization_id == actor.organization_id))
    if not row: raise HTTPException(404, "PM job card not found")
    return row

@router.patch("/{card_id}", response_model=PMJobCardRead)
async def update_card(card_id: uuid.UUID, body: PMJobCardUpdate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    row = await session.scalar(select(PMJobCard).where(PMJobCard.id == card_id, PMJobCard.organization_id == actor.organization_id))
    if not row: raise HTTPException(404, "PM job card not found")
    if row.created_at < datetime.now(timezone.utc) - timedelta(days=10):
        raise HTTPException(409, "Job cards can only be edited within 10 days of creation")
    changes = body.model_dump(exclude_unset=True)
    asset_id = changes.get("asset_id", row.asset_id)
    if asset_id:
        asset = await session.scalar(select(Asset).where(Asset.id == asset_id, Asset.organization_id == actor.organization_id))
        if not asset:
            raise HTTPException(404, "Equipment not found")
    site_id = changes.get("site_location_id", row.site_location_id)
    project_id = changes.get("project_id", row.project_id)
    if site_id:
        site = await session.scalar(select(Location).where(Location.id == site_id, Location.organization_id == actor.organization_id))
        if not site:
            raise HTTPException(404, "Selected project site not found")
        if project_id and site.project_id != project_id:
            raise HTTPException(422, "Selected site does not belong to this project")
    number = changes.get("job_card_number")
    if number and number != row.job_card_number:
        duplicate = await session.scalar(select(PMJobCard.id).where(PMJobCard.organization_id == actor.organization_id, PMJobCard.job_card_number == number, PMJobCard.id != row.id).limit(1))
        if duplicate:
            raise HTTPException(409, "That PM Job Card No. is already in use. Choose another number.")
    if changes.get("work_order_id") and not asset_id:
        raise HTTPException(422, "A saved work order can only be linked to selected registered equipment.")
    if changes.get("work_order_id"):
        work_order = await session.scalar(select(MaintenanceWorkOrder).where(MaintenanceWorkOrder.id == changes["work_order_id"], MaintenanceWorkOrder.organization_id == actor.organization_id, MaintenanceWorkOrder.asset_id == asset_id))
        if not work_order:
            raise HTTPException(404, "Work order not found for this equipment")
    for key, value in changes.items(): setattr(row, key, value)
    row.updated_by_id = actor.id
    if row.status == "COMPLETED" and row.completed_at is None: row.completed_at = datetime.now(timezone.utc)
    await session.commit(); await session.refresh(row); return row
