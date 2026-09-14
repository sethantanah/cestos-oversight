import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import request_storage, require_permission
from app.core.storage import LocalStorage
from app.db.session import get_session
from app.models import User
from app.models.asset import AssetDocumentType as DocumentType
from app.models.asset import AssetStatus
from app.schemas.asset import (
    AssetAssignmentCreate,
    AssetAssignmentRead,
    AssetAssignmentUpdate,
    AssetCategoryCreate,
    AssetCategoryRead,
    AssetComponentCreate,
    AssetComponentRead,
    AssetCreate,
    AssetDocumentCreate,
    AssetDocumentRead,
    AssetMeterReadingCreate,
    AssetMeterReadingRead,
    AssetRead,
    AssetUpdate,
)
from app.schemas.common import Page
from app.services.equipment import EquipmentService as AssetService

router = APIRouter(prefix="/assets", tags=["assets"])

categories_router = APIRouter(prefix="/asset-categories", tags=["asset-categories"])

asset_assignments_router = APIRouter(prefix="/asset-assignments", tags=["assignments"])


@router.get("", response_model=Page[AssetRead])
async def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    category_id: uuid.UUID | None = None,
    status: AssetStatus | None = None,
    project_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    responsible_employee_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    unassigned_only: bool = False,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Page[AssetRead]:
    return await AssetService(session, actor).list(
        page,
        page_size,
        search,
        category_id,
        status,
        project_id,
        location_id,
        responsible_employee_id,
        is_active,
        unassigned_only,
    )


@router.post("", response_model=AssetRead, status_code=201)
async def create_asset(
    body: AssetCreate,
    request: Request,
    actor: User = Depends(require_permission("assets.create")),
    session: AsyncSession = Depends(get_session),
) -> AssetRead:
    return await AssetService(session, actor).create(body, request)


@router.get("/dashboard-summary")
async def fleet_dashboard_summary(
    status: AssetStatus | None = Query(None),
    category_id: uuid.UUID | None = Query(None),
    location_id: uuid.UUID | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from sqlalchemy import func, select
    from app.models.asset import Asset, AssetAssignment, AssetStatus
    from app.models.project import Project

    # 1. Total KPI counts by status
    status_stmt = (
        select(Asset.status, func.count(Asset.id))
        .where(Asset.organization_id == actor.organization_id, Asset.archived_at.is_(None))
    )
    if status:
        status_stmt = status_stmt.where(Asset.status == status)
    if category_id:
        status_stmt = status_stmt.where(Asset.category_id == category_id)
    if location_id:
        status_stmt = status_stmt.where(Asset.default_location_id == location_id)
    if date_from:
        status_stmt = status_stmt.where(Asset.created_at >= date_from)
    if date_to:
        status_stmt = status_stmt.where(Asset.created_at <= date_to)
    if project_id:
        proj_asset_subq = select(AssetAssignment.asset_id).where(
            AssetAssignment.organization_id == actor.organization_id,
            AssetAssignment.project_id == project_id,
            AssetAssignment.status == "ACTIVE",
        ).scalar_subquery()
        status_stmt = status_stmt.where(Asset.id.in_(proj_asset_subq))

    status_stmt = status_stmt.group_by(Asset.status)
    status_rows = (await session.execute(status_stmt)).all()
    counts = {getattr(r[0], "value", str(r[0])).upper(): int(r[1]) for r in status_rows}

    total = sum(counts.values())
    operating = counts.get("OPERATING", 0) + counts.get("ASSIGNED", 0)
    available = counts.get("AVAILABLE", 0)
    standby = counts.get("STANDBY", 0) + counts.get("MOBILIZING", 0)
    breakdown = counts.get("BREAKDOWN", 0)
    maintenance = counts.get("UNDER_MAINTENANCE", 0) + counts.get("MAINTENANCE", 0)
    out_of_service = counts.get("OUT_OF_SERVICE", 0) + counts.get("DISPOSED", 0) + counts.get("QUARANTINED", 0)

    # 2. Fleet by Project distribution
    proj_stmt = (
        select(
            Project.name.label("project"),
            Asset.status.label("asset_status"),
            func.count(func.distinct(AssetAssignment.asset_id)).label("count"),
        )
        .join(Project, AssetAssignment.project_id == Project.id)
        .join(Asset, AssetAssignment.asset_id == Asset.id)
        .where(
            AssetAssignment.organization_id == actor.organization_id,
            AssetAssignment.status == "ACTIVE",
            Asset.archived_at.is_(None),
        )
    )
    if project_id:
        proj_stmt = proj_stmt.where(Project.id == project_id)
    if category_id:
        proj_stmt = proj_stmt.where(Asset.category_id == category_id)
    if location_id:
        proj_stmt = proj_stmt.where(Asset.default_location_id == location_id)
    if status:
        proj_stmt = proj_stmt.where(Asset.status == status)

    proj_stmt = proj_stmt.group_by(Project.name, Project.id, Asset.status).order_by(
        func.count(func.distinct(AssetAssignment.asset_id)).desc()
    )
    proj_rows = (await session.execute(proj_stmt)).all()

    project_map: dict[str, dict[str, Any]] = {}
    for r in proj_rows:
        p_name = str(r.project)
        st = getattr(r.asset_status, "value", str(r.asset_status)).upper()
        if p_name not in project_map:
            project_map[p_name] = {
                "project": p_name,
                "count": 0,
                "operating": 0,
                "standby": 0,
                "breakdown": 0,
            }
        cnt = int(r.count)
        project_map[p_name]["count"] += cnt
        if st in ("OPERATING", "ASSIGNED"):
            project_map[p_name]["operating"] += cnt
        elif st in ("STANDBY", "MOBILIZING", "UNDER_MAINTENANCE", "MAINTENANCE"):
            project_map[p_name]["standby"] += cnt
        elif st in ("BREAKDOWN", "OUT_OF_SERVICE", "QUARANTINED", "LOST", "STOLEN"):
            project_map[p_name]["breakdown"] += cnt
        else:
            project_map[p_name]["operating"] += cnt

    by_project = list(project_map.values())

    # Include unassigned active assets
    if not project_id:
        assigned_subq = (
            select(AssetAssignment.asset_id)
            .where(
                AssetAssignment.organization_id == actor.organization_id,
                AssetAssignment.status == "ACTIVE",
            )
            .scalar_subquery()
        )
        unassigned_stmt = select(Asset.status, func.count(Asset.id)).where(
            Asset.organization_id == actor.organization_id,
            Asset.archived_at.is_(None),
            ~Asset.id.in_(assigned_subq),
        )
        if category_id:
            unassigned_stmt = unassigned_stmt.where(Asset.category_id == category_id)
        if location_id:
            unassigned_stmt = unassigned_stmt.where(Asset.default_location_id == location_id)
        if status:
            unassigned_stmt = unassigned_stmt.where(Asset.status == status)

        unassigned_stmt = unassigned_stmt.group_by(Asset.status)
        u_rows = (await session.execute(unassigned_stmt)).all()
        if u_rows:
            u_entry = {
                "project": "Main Yard / Unassigned",
                "count": 0,
                "operating": 0,
                "standby": 0,
                "breakdown": 0,
            }
            for u in u_rows:
                st = getattr(u[0], "value", str(u[0])).upper()
                cnt = int(u[1])
                u_entry["count"] += cnt
                if st in ("OPERATING", "ASSIGNED", "AVAILABLE"):
                    u_entry["operating"] += cnt
                elif st in ("STANDBY", "MOBILIZING", "UNDER_MAINTENANCE", "MAINTENANCE"):
                    u_entry["standby"] += cnt
                else:
                    u_entry["breakdown"] += cnt
            if u_entry["count"] > 0:
                by_project.append(u_entry)

    return {
        "total": total,
        "operating": operating,
        "available": available,
        "standby": standby,
        "breakdown": breakdown,
        "under_maintenance": maintenance,
        "maintenance": maintenance,
        "out_of_service": out_of_service,
        "total_assets": total,
        "operating_assets": operating,
        "available_assets": available,
        "standby_assets": standby,
        "breakdown_assets": breakdown,
        "maintenance_assets": maintenance,
        "under_maintenance_assets": maintenance,
        "out_of_service_assets": out_of_service,
        "critical_open_defects": 0,
        "by_project": by_project,
    }


@router.get("/insurance/expiring")
async def get_expiring_insurance(
    days: int = 30,
    actor: User = Depends(require_permission("assets.insurance.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).get_expiring_insurance(days)


@router.get("/registrations/expiring")
async def get_expiring_registrations(
    days: int = 30,
    actor: User = Depends(require_permission("assets.registration.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).get_expiring_registrations(days)


@router.get("/expiring-documents")
async def get_expiring_documents_and_deadlines(
    days: int = 60,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).get_expiring_documents_and_deadlines(days)


@router.get("/defects/critical")
async def get_critical_defects(
    actor: User = Depends(require_permission("assets.defects.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).get_critical_defects()


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> AssetRead:
    return await AssetService(session, actor).get(asset_id)


@router.patch("/{asset_id}", response_model=AssetRead)
async def update_asset(
    asset_id: uuid.UUID,
    body: AssetUpdate,
    request: Request,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> AssetRead:
    return await AssetService(session, actor).update(asset_id, body, request)


@router.post("/{asset_id}/archive", response_model=AssetRead)
async def archive_asset(
    asset_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("assets.archive")),
    session: AsyncSession = Depends(get_session),
) -> AssetRead:
    return await AssetService(session, actor).archive(asset_id, request)


@router.get("/{asset_id}/overview")
async def asset_overview(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await AssetService(session, actor).overview(asset_id)


@router.get("/{asset_id}/assignments", response_model=list[AssetAssignmentRead])
async def list_asset_assignments(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[AssetAssignmentRead]:
    return await AssetService(session, actor).list_assignments(asset_id)


@router.post("/{asset_id}/assignments", response_model=AssetAssignmentRead, status_code=201)
async def create_asset_assignment(
    asset_id: uuid.UUID,
    body: AssetAssignmentCreate,
    request: Request,
    actor: User = Depends(require_permission("assets.assign")),
    session: AsyncSession = Depends(get_session),
) -> AssetAssignmentRead:
    return await AssetService(session, actor).create_assignment(asset_id, body, request)


@router.get("/{asset_id}/meter-readings", response_model=list[AssetMeterReadingRead])
async def list_asset_meter_readings(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[AssetMeterReadingRead]:
    return await AssetService(session, actor).list_meter_readings(asset_id)


@router.post(
    "/{asset_id}/meter-readings",
    response_model=AssetMeterReadingRead,
    status_code=201,
)
async def record_asset_meter_reading(
    asset_id: uuid.UUID,
    body: AssetMeterReadingCreate,
    request: Request,
    actor: User = Depends(require_permission("assets.meter.record")),
    session: AsyncSession = Depends(get_session),
) -> AssetMeterReadingRead:
    return await AssetService(session, actor).record_meter_reading(asset_id, body, request)


@router.get("/{asset_id}/components", response_model=list[AssetComponentRead])
async def list_asset_components(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.components.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[AssetComponentRead]:
    return await AssetService(session, actor).list_components(asset_id)


@router.post("/{asset_id}/components", response_model=AssetComponentRead, status_code=201)
async def add_asset_component(
    asset_id: uuid.UUID,
    body: AssetComponentCreate,
    actor: User = Depends(require_permission("assets.components.manage")),
    session: AsyncSession = Depends(get_session),
) -> AssetComponentRead:
    return await AssetService(session, actor).add_component(asset_id, body)


@router.get("/{asset_id}/documents", response_model=list[AssetDocumentRead])
async def list_asset_documents(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("asset_documents.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[AssetDocumentRead]:
    return await AssetService(session, actor).list_documents(asset_id)


@router.post("/{asset_id}/documents", response_model=AssetDocumentRead, status_code=201)
async def add_asset_document(
    asset_id: uuid.UUID,
    body: AssetDocumentCreate,
    request: Request,
    actor: User = Depends(require_permission("asset_documents.manage")),
    session: AsyncSession = Depends(get_session),
) -> AssetDocumentRead:
    return await AssetService(session, actor).add_document(asset_id, body, request)


@router.post(
    "/{asset_id}/documents/upload",
    response_model=AssetDocumentRead,
    status_code=201,
)
async def upload_asset_document(
    asset_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(DocumentType.OTHER),
    title: str | None = Form(None),
    document_number: str | None = Form(None),
    issue_date: date | None = Form(None),
    expiry_date: date | None = Form(None),
    issuing_authority: str | None = Form(None),
    notes: str | None = Form(None),
    actor: User = Depends(require_permission("asset_documents.manage")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> AssetDocumentRead:
    data = await file.read(storage.max_bytes + 1)
    return await AssetService(session, actor).upload_document(
        asset_id,
        data,
        file.filename,
        file.content_type,
        storage,
        document_type=document_type,
        title=title,
        document_number=document_number,
        issue_date=issue_date,
        expiry_date=expiry_date,
        issuing_authority=issuing_authority,
        notes=notes,
        request=request,
    )


@router.get("/{asset_id}/documents/{document_id}/download")
async def download_asset_document(
    asset_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: User = Depends(require_permission("asset_documents.read")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> FileResponse:
    path, media_type, filename = await AssetService(session, actor).download_document(
        asset_id, document_id, storage
    )
    return FileResponse(path, media_type=media_type, filename=filename)


@categories_router.get("", response_model=list[AssetCategoryRead])
async def list_asset_categories(
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[AssetCategoryRead]:
    return await AssetService(session, actor).list_categories()


@categories_router.post("", response_model=AssetCategoryRead, status_code=201)
async def create_asset_category(
    body: AssetCategoryCreate,
    actor: User = Depends(require_permission("assets.create")),
    session: AsyncSession = Depends(get_session),
) -> AssetCategoryRead:
    return await AssetService(session, actor).create_category(body)


@asset_assignments_router.patch("/{assignment_id}", response_model=AssetAssignmentRead)
async def update_asset_assignment(
    assignment_id: uuid.UUID,
    body: AssetAssignmentUpdate,
    request: Request,
    actor: User = Depends(require_permission("assets.assign")),
    session: AsyncSession = Depends(get_session),
) -> AssetAssignmentRead:
    return await AssetService(session, actor).update_assignment(assignment_id, body, request)


# ---- location history ----


@router.get("/{asset_id}/location-history")
async def get_asset_location_history(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).list_location_history(asset_id)


@router.post("/{asset_id}/location-events", status_code=201)
async def record_asset_location_event(
    asset_id: uuid.UUID,
    body: dict,
    request: Request,
    actor: User = Depends(require_permission("assets.transfer")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).record_location_event(
        asset_id,
        body["location_id"],
        body["event_type"],
        body.get("project_id"),
        body.get("meter_reading"),
        body.get("notes"),
        request,
    )


# ---- status history ----


@router.post("/{asset_id}/status", response_model=AssetRead)
async def change_asset_status(
    asset_id: uuid.UUID,
    body: dict,
    request: Request,
    actor: User = Depends(require_permission("assets.status.change")),
    session: AsyncSession = Depends(get_session),
) -> AssetRead:
    return await AssetService(session, actor).change_status(
        asset_id, body["new_status"], body.get("reason"), request
    )


# ---- insurance ----


@router.get("/{asset_id}/insurance")
async def get_asset_insurance(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.insurance.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).list_insurance(asset_id)


@router.post("/{asset_id}/insurance", status_code=201)
async def add_asset_insurance(
    asset_id: uuid.UUID,
    body: dict,
    request: Request,
    actor: User = Depends(require_permission("assets.insurance.manage")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).add_insurance(
        asset_id,
        body["provider"],
        body["policy_number"],
        body["start_date"],
        body["expiry_date"],
        body.get("coverage_type"),
        body.get("coverage_amount"),
        body.get("currency"),
        body.get("premium_amount"),
        body.get("notes"),
        request,
    )


# ---- registration ----


@router.get("/{asset_id}/registrations")
async def get_asset_registrations(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.registration.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).list_registrations(asset_id)


@router.post("/{asset_id}/registrations", status_code=201)
async def add_asset_registration(
    asset_id: uuid.UUID,
    body: dict,
    request: Request,
    actor: User = Depends(require_permission("assets.registration.manage")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).add_registration(
        asset_id,
        body["registration_type"],
        body["registration_number"],
        body.get("issuing_authority"),
        body.get("issue_date"),
        body.get("expiry_date"),
        body.get("notes"),
        request,
    )


# ---- inspections ----


@router.get("/{asset_id}/inspections")
async def get_asset_inspections(
    asset_id: uuid.UUID,
    inspection_type: str | None = None,
    condition_status: str | None = None,
    actor: User = Depends(require_permission("assets.inspections.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).list_inspections(
        asset_id, inspection_type, condition_status
    )


@router.post("/{asset_id}/inspections", status_code=201)
async def create_asset_inspection(
    asset_id: uuid.UUID,
    body: dict,
    request: Request,
    actor: User = Depends(require_permission("assets.inspections.manage")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).create_inspection(
        asset_id,
        body["inspection_type"],
        body["condition_status"],
        body.get("project_id"),
        body.get("location_id"),
        body.get("meter_reading"),
        body.get("summary"),
        body.get("defects_found", False),
        body.get("defect_notes"),
        body.get("follow_up_required", False),
        request,
    )


# ---- defects ----


@router.get("/{asset_id}/defects")
async def get_asset_defects(
    asset_id: uuid.UUID,
    status: str | None = None,
    severity: str | None = None,
    actor: User = Depends(require_permission("assets.defects.read")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).list_defects(asset_id, status, severity)


@router.post("/{asset_id}/defects", status_code=201)
async def report_asset_defect(
    asset_id: uuid.UUID,
    body: dict,
    request: Request,
    actor: User = Depends(require_permission("assets.defects.manage")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).report_defect(
        asset_id,
        body["severity"],
        body["description"],
        body.get("inspection_id"),
        body.get("notes"),
        request,
    )


@router.patch("/{asset_id}/defects/{defect_id}")
async def update_asset_defect(
    asset_id: uuid.UUID,
    defect_id: uuid.UUID,
    body: dict,
    actor: User = Depends(require_permission("assets.defects.manage")),
    session: AsyncSession = Depends(get_session),
):
    return await AssetService(session, actor).update_defect(asset_id, defect_id, body)


@router.post("/{asset_id}/defects/{defect_id}/resolve")
async def resolve_asset_defect(
    asset_id: uuid.UUID,
    defect_id: uuid.UUID,
    body: dict | None = None,
    request: Request = None,
    actor: User = Depends(require_permission("assets.defects.manage")),
    session: AsyncSession = Depends(get_session),
):
    notes = body.get("notes") if body else None
    service = AssetService(session, actor)
    from app.models.asset_records import AssetDefect

    await service.ref(AssetDefect, defect_id, asset_id)
    return await service.resolve_equipment_defect(defect_id, notes or "Resolved")
