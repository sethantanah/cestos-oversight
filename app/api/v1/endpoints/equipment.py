"""Equipment phase routes. Static fleet routes precede /assets/{asset_id}."""

import math
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_current_active_user, require_permission
from app.core.exceptions import NotFoundError, ValidationError
from app.db.session import get_session
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetComponent,
    AssetDocument,
    AssetMeterReading,
    User,
)
from app.models.asset import AssetStatus, ComponentStatus, MeterType, OwnershipType
from app.models.asset_records import AssetDefect, AssetMedia
from app.models.employee import AssignmentStatus
from app.schemas import equipment as schemas
from app.schemas.asset import AssetAssignmentUpdate, AssetComponentCreate
from app.services.equipment import RECORDS, EquipmentService

router = APIRouter(tags=["equipment"])


@router.get("/assets")
async def asset_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    category_id: uuid.UUID | None = None,
    status: AssetStatus | None = None,
    ownership_type: OwnershipType | None = None,
    project_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    responsible_employee_id: uuid.UUID | None = None,
    primary_operator_id: uuid.UUID | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    registration_number: str | None = None,
    serial_number: str | None = None,
    is_active: bool | None = None,
    is_available: bool | None = None,
    unassigned_only: bool = False,
    operational_eligibility: str | None = None,
    document_expiring_within_days: int | None = Query(None, ge=0, le=3650),
    insurance_expiring_within_days: int | None = Query(None, ge=0, le=3650),
    registration_expiring_within_days: int | None = Query(None, ge=0, le=3650),
    has_open_defects: bool | None = None,
    has_critical_defects: bool | None = None,
    sort: str = Query("asset_number", pattern="^(asset_number|name|status|manufacturer)$"),
    descending: bool = False,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    filters = locals().copy()
    rows = await EquipmentService(session, actor).filtered_assets(filters)
    rows.sort(key=lambda row: str(row.get(sort) or ""), reverse=descending)
    return {
        "items": rows[(page - 1) * page_size : page * page_size],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(len(rows) / page_size),
    }


@router.get("/assets/available")
async def available_assets(
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    meter_type: MeterType | None = None,
    ownership_type: OwnershipType | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await EquipmentService(session, actor).filtered_assets(
        {**locals(), "is_available": True}
    )
    return {
        "items": rows[(page - 1) * page_size : page * page_size],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(len(rows) / page_size),
    }


@router.get("/assets/lookup")
async def lookup(
    code: str,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from sqlalchemy import or_

    service = EquipmentService(session, actor)
    row = await session.scalar(
        select(Asset).where(
            Asset.organization_id == actor.organization_id,
            or_(
                Asset.asset_number == code, Asset.qr_code_value == code, Asset.barcode_value == code
            ),
        )
    )
    if row is None:
        raise NotFoundError("Asset not found")
    return await service.overview(row.id)


@router.get("/assets/dashboard-summary")
async def dashboard(
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await EquipmentService(session, actor).fleet_summary()


@router.get("/projects/{project_id}/equipment-summary")
async def project_equipment(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await EquipmentService(session, actor).fleet_summary(project_id)


@router.post("/assets/{asset_id}/restore")
async def restore(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.archive")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).restore(asset_id)


@router.post("/assets/{asset_id}/status")
async def status(
    asset_id: uuid.UUID,
    body: schemas.StatusChange,
    actor: User = Depends(require_permission("assets.status.change")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).change_status(asset_id, body)


@router.post("/assets/{asset_id}/transfer")
async def transfer(
    asset_id: uuid.UUID,
    body: schemas.AssetTransfer,
    actor: User = Depends(require_permission("assets.transfer")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).transfer(asset_id, body)


@router.post("/assets/{asset_id}/meter-reset")
async def reset(
    asset_id: uuid.UUID,
    body: schemas.MeterReset,
    actor: User = Depends(require_permission("assets.meter.override")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).reset_meter(asset_id, body)


@router.get("/assets/{asset_id}/activity")
async def activity(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.audit.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).activity(asset_id)


@router.get("/asset-categories/{identifier}")
async def category(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    return service.public(await service.ref(AssetCategory, identifier))


@router.patch("/asset-categories/{identifier}")
async def category_update(
    identifier: uuid.UUID,
    body: schemas.CategoryUpdate,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).update_category(
        identifier, body.model_dump(exclude_unset=True)
    )


@router.post("/asset-categories/{identifier}/archive")
async def category_archive(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.archive")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).update_category(identifier, {"is_active": False})


@router.get("/asset-assignments/{identifier}")
async def assignment(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    return service.public(await service.ref(AssetAssignment, identifier))


@router.post("/asset-assignments/{identifier}/complete")
async def complete(
    identifier: uuid.UUID,
    body: AssetAssignmentUpdate,
    actor: User = Depends(require_permission("assets.assign")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).update_assignment(
        identifier, body.model_copy(update={"status": AssignmentStatus.COMPLETED})
    )


@router.post("/asset-assignments/{identifier}/cancel")
async def cancel(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.assign")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).update_assignment(
        identifier, AssetAssignmentUpdate(status=AssignmentStatus.CANCELLED)
    )


@router.get("/asset-meter-readings/{identifier}")
async def meter(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.meter.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    return service.public(await service.ref(AssetMeterReading, identifier))


@router.get("/asset-components/{identifier}")
async def component(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.components.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    return service.public(await service.ref(AssetComponent, identifier))


@router.patch("/asset-components/{identifier}")
async def component_update(
    identifier: uuid.UUID,
    body: schemas.ComponentUpdate,
    actor: User = Depends(require_permission("assets.components.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).change_component(
        identifier, body.model_dump(exclude_unset=True)
    )


@router.post("/asset-components/{identifier}/replace")
async def component_replace(
    identifier: uuid.UUID,
    body: AssetComponentCreate,
    actor: User = Depends(require_permission("assets.components.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).change_component(
        identifier, body.model_dump(), True
    )


@router.post("/asset-components/{identifier}/remove")
async def component_remove(
    identifier: uuid.UUID,
    body: schemas.ComponentRemoval,
    actor: User = Depends(require_permission("assets.components.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).change_component(
        identifier, {**body.model_dump(), "status": ComponentStatus.REMOVED, "is_active": False}
    )


def related_routes(
    kind: str, item: str, create_schema: Any, update_schema: Any, permission: str
) -> None:
    async def listing(
        asset_id: uuid.UUID,
        actor: User = Depends(require_permission(permission + ".read")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await EquipmentService(session, actor).list_records(asset_id, kind)

    listing.__name__ = kind.replace("-", "_") + "_list"
    router.add_api_route("/assets/{asset_id}/" + kind, listing, methods=["GET"])

    async def create(
        asset_id: uuid.UUID,
        body: Any,
        actor: User = Depends(require_permission(permission + ".manage")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        return await EquipmentService(session, actor).add_record(asset_id, kind, body)

    create.__annotations__["body"] = create_schema
    create.__name__ = kind.replace("-", "_") + "_create"
    router.add_api_route(
        "/assets/{asset_id}/" + ("location-events" if kind == "location-history" else kind),
        create,
        methods=["POST"],
        status_code=201,
    )
    if update_schema:

        async def patch(
            identifier: uuid.UUID,
            body: Any,
            actor: User = Depends(require_permission(permission + ".manage")),
            session: AsyncSession = Depends(get_session),
        ) -> Any:
            return await EquipmentService(session, actor).update_record(identifier, kind, body)

        patch.__annotations__["body"] = update_schema
        patch.__name__ = kind.replace("-", "_") + "_update"
        router.add_api_route("/" + item + "/{identifier}", patch, methods=["PATCH"])

    async def get(
        identifier: uuid.UUID,
        actor: User = Depends(require_permission(permission + ".read")),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        service = EquipmentService(session, actor)
        return service.public(await service.ref(RECORDS[kind], identifier))

    get.__name__ = kind.replace("-", "_") + "_get"
    router.add_api_route("/" + item + "/{identifier}", get, methods=["GET"])


def expiry_route(path: str, model: Any, permission: str) -> None:
    async def expiring(
        days: int = Query(30, ge=0, le=3650),
        expired: bool = False,
        actor: User = Depends(require_permission(permission)),
        session: AsyncSession = Depends(get_session),
    ) -> Any:
        service = EquipmentService(session, actor)
        query = select(model).where(
            model.organization_id == actor.organization_id,
            model.expiry_date < date.today()
            if expired
            else model.expiry_date <= date.today() + timedelta(days=days),
        )
        if hasattr(model, "is_active"):
            query = query.where(model.is_active.is_(True))
        elif hasattr(model, "status"):
            query = query.where(model.status.notin_(["CANCELLED", "PENDING"]))
        return [
            service.public(row)
            for row in (await session.scalars(query.order_by(model.expiry_date))).all()
        ]

    expiring.__name__ = path.replace("/", "_").replace("-", "_")
    router.add_api_route(path, expiring, methods=["GET"])


expiry_route("/asset-documents/expiring", AssetDocument, "assets.documents.read")
expiry_route("/asset-insurance/expiring", RECORDS["insurance"], "assets.insurance.read")
expiry_route("/asset-registrations/expiring", RECORDS["registrations"], "assets.registration.read")


@router.get("/asset-defects/open")
@router.get("/asset-defects/critical")
async def defects(
    request: Request,
    actor: User = Depends(require_permission("assets.defects.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    query = select(AssetDefect).where(
        AssetDefect.organization_id == actor.organization_id,
        AssetDefect.status.in_(["OPEN", "ACKNOWLEDGED"]),
    )
    if request.url.path.endswith("/critical"):
        query = query.where(AssetDefect.severity == "CRITICAL")
    service = EquipmentService(session, actor)
    return [
        service.public(row)
        for row in (await session.scalars(query.order_by(AssetDefect.reported_at.desc()))).all()
    ]


related_routes(
    "insurance",
    "asset-insurance",
    schemas.InsuranceCreate,
    schemas.InsuranceUpdate,
    "assets.insurance",
)
related_routes(
    "registrations",
    "asset-registrations",
    schemas.RegistrationCreate,
    schemas.RegistrationUpdate,
    "assets.registration",
)
related_routes("ownership", "asset-ownership", schemas.OwnershipCreate, None, "assets.ownership")
related_routes("media", "asset-media", schemas.MediaCreate, schemas.MediaUpdate, "assets.media")
related_routes(
    "inspections",
    "asset-inspections",
    schemas.InspectionCreate,
    schemas.InspectionUpdate,
    "assets.inspections",
)
related_routes(
    "defects", "asset-defects", schemas.DefectCreate, schemas.DefectUpdate, "assets.defects"
)
related_routes(
    "location-history", "asset-location-events", schemas.LocationEvent, None, "assets.location"
)


@router.get("/assets/{asset_id}/status-history")
async def status_history(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).list_records(asset_id, "status-history")


@router.post("/asset-defects/{identifier}/resolve")
async def resolve_defect(
    identifier: uuid.UUID,
    body: schemas.ResolveDefect,
    actor: User = Depends(require_permission("assets.defects.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).resolve_equipment_defect(identifier, body.notes)


@router.post("/asset-media/{identifier}/set-primary")
async def primary_media(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.media.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).primary_media(identifier)


@router.post("/asset-media/{identifier}/archive")
async def archive_media(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.media.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await EquipmentService(session, actor).primary_media(identifier, True)


@router.post("/assets/{asset_id}/media/upload", status_code=201)
async def upload_media(
    asset_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    actor: User = Depends(require_permission("assets.media.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id, True)
    storage = request.app.state.storage
    from pathlib import Path

    if Path(file.filename or "").suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValidationError("Upload a PNG or JPEG photo")
    data = await file.read(storage.max_bytes + 1)
    if not data:
        raise ValidationError("Photo is empty")
    try:
        stored = await run_in_threadpool(
            storage.save,
            f"asset-media/{actor.organization_id}/{asset_id}",
            data,
            file.filename or "",
            file.content_type,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error
    try:
        row = AssetMedia(
            organization_id=actor.organization_id,
            asset_id=asset_id,
            media_type="PHOTO",
            file_url="pending",
            storage_path=stored.relative_path,
            file_name=stored.filename,
            caption=caption,
            uploaded_by_id=actor.id,
        )
        session.add(row)
        await session.flush()
        row.file_url = f"/api/v1/asset-media/{row.id}/download"
        service.audit("asset.media_added", asset_id, row)
        await service.commit()
        return service.public(row)
    except BaseException:
        await run_in_threadpool(storage.delete, stored.relative_path)
        raise


@router.get("/asset-media/{identifier}/download")
async def download_media(
    identifier: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("assets.media.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await EquipmentService(session, actor).ref(AssetMedia, identifier)
    if not row.storage_path or not row.is_active:
        raise NotFoundError("Photo unavailable")
    path = request.app.state.storage.resolve(row.storage_path)
    if not path.is_file():
        raise NotFoundError("Photo unavailable")
    return FileResponse(path, filename=row.file_name, media_type="application/octet-stream")


@router.get("/asset-documents/{identifier}")
async def document(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.documents.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    return service.public(await service.ref(AssetDocument, identifier))


@router.patch("/asset-documents/{identifier}")
async def document_update(
    identifier: uuid.UUID,
    body: schemas.DocumentUpdate,
    actor: User = Depends(require_permission("assets.documents.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    row = await service.ref(AssetDocument, identifier, lock=True)
    data = body.model_dump(exclude_unset=True)
    await service.validate_fields({**service.public(row), **data}, row.asset_id)
    for key, value in data.items():
        setattr(row, key, value)
    row.verification_status = "PENDING"
    row.verified_by_id = None
    row.verified_at = None
    service.audit("asset.document_updated", row.asset_id, row)
    await service.commit()
    return service.public(row)


@router.post("/asset-documents/{identifier}/verify")
async def verify_document(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.documents.verify")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    from datetime import UTC

    service = EquipmentService(session, actor)
    row = await service.ref(AssetDocument, identifier, lock=True)
    if not row.is_active:
        raise ValidationError("Archived documents cannot be verified")
    row.verification_status = "VERIFIED"
    row.verified_by_id = actor.id
    row.verified_at = datetime.now(UTC)
    service.audit("asset.document_verified", row.asset_id, row)
    await service.commit()
    return service.public(row)


@router.post("/asset-documents/{identifier}/archive")
async def archive_document(
    identifier: uuid.UUID,
    actor: User = Depends(require_permission("assets.documents.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    row = await service.ref(AssetDocument, identifier, lock=True)
    row.is_active = False
    service.audit("asset.document_archived", row.asset_id, row)
    await service.commit()
    return service.public(row)


@router.get("/equipment/access")
async def equipment_access(actor: User = Depends(get_current_active_user)) -> Any:
    from app.core.dependencies import scoped_roles

    return {
        "superadmin": actor.is_superuser,
        "permissions": [p.code for r in scoped_roles(actor) for p in r.permissions],
    }
