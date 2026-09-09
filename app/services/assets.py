from typing import Any
import decimal
import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.storage import LocalStorage
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetComponent,
    AssetDefect,
    AssetDocument,
    AssetInspection,
    AssetInsurance,
    AssetLocationHistory,
    AssetMedia,
    AssetMeterReading,
    AssetOwnership,
    AssetRegistration,
    AssetStatusHistory,
    Employee,
    Location,
    Project,
    User,
)
from app.models.asset import AssetStatus
from app.models.employee import AssignmentStatus
from app.models.asset import AssetDocumentType as DocumentType
from app.repositories.base import organization_query
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
    AssetOverview,
    AssetRead,
    AssetUpdate,
)
from app.schemas.common import Page
from app.schemas.employee import EmployeeRead
from app.schemas.location import LocationRead
from app.services.audit import RequestMetadata, record_audit, request_metadata
from app.services.counters import next_business_number


def _meta(request: Request | None) -> RequestMetadata:
    if request is None:
        return {"ip_address": None, "user_agent": None}
    return request_metadata(request)


class AssetService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def _scope(self) -> Select[tuple[Asset]]:
        return organization_query(Asset, self.actor.organization_id)

    async def _get_or_404(self, asset_id: uuid.UUID) -> Asset:
        asset = (
            await self.session.scalars(self._scope().where(Asset.id == asset_id))
        ).one_or_none()
        if asset is None:
            raise NotFoundError("Asset not found")
        return asset

    async def get(self, asset_id: uuid.UUID) -> AssetRead:
        return AssetRead.model_validate(await self._get_or_404(asset_id))

    async def list(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        status: AssetStatus | None = None,
        project_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        responsible_employee_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        unassigned_only: bool = False,
    ) -> Page[AssetRead]:
        query = self._scope()
        if search:
            like = f"%{search}%"
            query = query.where(
                or_(
                    Asset.asset_number.ilike(like),
                    Asset.name.ilike(like),
                    Asset.serial_number.ilike(like),
                    Asset.registration_number.ilike(like),
                    Asset.manufacturer.ilike(like),
                    Asset.model.ilike(like),
                )
            )
        if category_id is not None:
            query = query.where(Asset.category_id == category_id)
        if status is not None:
            query = query.where(Asset.status == status)
        if responsible_employee_id is not None:
            query = query.where(Asset.responsible_employee_id == responsible_employee_id)
        if location_id is not None:
            query = query.where(Asset.default_location_id == location_id)
        if is_active is not None:
            query = query.where(Asset.is_active == is_active)
        if project_id is not None or unassigned_only:
            active = select(AssetAssignment.asset_id).where(
                AssetAssignment.organization_id == self.actor.organization_id,
                AssetAssignment.status == AssignmentStatus.ACTIVE,
            )
            if project_id is not None:
                active = active.where(AssetAssignment.project_id == project_id)
            assigned_ids = set((await self.session.scalars(active)).all())
            if unassigned_only:
                if assigned_ids:
                    query = query.where(Asset.id.notin_(assigned_ids))
            elif project_id is not None:
                if not assigned_ids:
                    return Page(items=[], total=0, page=page, page_size=page_size, pages=0)
                query = query.where(Asset.id.in_(assigned_ids))
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await self.session.scalars(
                query.order_by(Asset.created_at, Asset.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [AssetRead.model_validate(row) for row in rows]
        return Page(
            items=items,
            total=total or 0,
            page=page,
            page_size=page_size,
            pages=math.ceil((total or 0) / page_size) if page_size else 0,
        )

    async def _validate_refs(
        self,
        category_id: uuid.UUID | None = None,
        default_location_id: uuid.UUID | None = None,
        responsible_employee_id: uuid.UUID | None = None,
    ) -> None:
        if category_id is not None:
            category = (
                await self.session.scalars(
                    select(AssetCategory).where(
                        AssetCategory.id == category_id,
                        AssetCategory.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if category is None:
                raise NotFoundError("Asset category not found")
        if default_location_id is not None:
            location = (
                await self.session.scalars(
                    select(Location).where(
                        Location.id == default_location_id,
                        Location.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if location is None:
                raise NotFoundError("Location not found")
        if responsible_employee_id is not None:
            employee = (
                await self.session.scalars(
                    select(Employee).where(
                        Employee.id == responsible_employee_id,
                        Employee.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if employee is None:
                raise NotFoundError("Responsible employee not found")

    async def create(self, body: AssetCreate, request: Request | None = None) -> AssetRead:
        try:
            await self._validate_refs(
                body.category_id, body.default_location_id, body.responsible_employee_id
            )
            number = await next_business_number(self.session, self.actor.organization_id, "asset")
            asset = Asset(
                organization_id=self.actor.organization_id,
                asset_number=number,
                category_id=body.category_id,
                name=body.name,
                description=body.description,
                manufacturer=body.manufacturer,
                model=body.model,
                serial_number=body.serial_number,
                year_of_manufacture=body.year_of_manufacture,
                purchase_date=body.purchase_date,
                purchase_price=body.purchase_price,
                ownership_type=body.ownership_type,
                engine_number=body.engine_number,
                registration_number=body.registration_number,
                meter_type=body.meter_type,
                current_meter_reading=body.current_meter_reading,
                status=body.status,
                default_location_id=body.default_location_id,
                responsible_employee_id=body.responsible_employee_id,
                photo_url=str(body.photo_url) if body.photo_url else None,
                warranty_expiry_date=body.warranty_expiry_date,
                insurance_expiry_date=body.insurance_expiry_date,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(asset)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.created",
                entity_type="asset",
                entity_id=asset.id,
                new_values={"asset_number": number, "name": body.name},
                **_meta(request),
            )
            await self.session.commit()
            return AssetRead.model_validate(asset)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, asset_id: uuid.UUID, body: AssetUpdate, request: Request | None = None
    ) -> AssetRead:
        try:
            asset = await self._get_or_404(asset_id)
            data = body.model_dump(exclude_unset=True)
            await self._validate_refs(
                data.get("category_id"),
                data.get("default_location_id"),
                data.get("responsible_employee_id"),
            )
            for key, value in data.items():
                setattr(asset, key, value)
            asset.updated_by_id = self.actor.id
            asset.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.updated",
                entity_type="asset",
                entity_id=asset.id,
                new_values={"asset_number": asset.asset_number},
                **_meta(request),
            )
            await self.session.commit()
            return AssetRead.model_validate(asset)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def archive(self, asset_id: uuid.UUID, request: Request | None = None) -> AssetRead:
        try:
            asset = await self._get_or_404(asset_id)
            if asset.archived_at is not None or not asset.is_active:
                raise ConflictError("Asset is already archived")
            asset.is_active = False
            asset.archived_at = datetime.now(UTC)
            asset.updated_by_id = self.actor.id
            asset.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.archived",
                entity_type="asset",
                entity_id=asset.id,
                new_values={"asset_number": asset.asset_number},
                **_meta(request),
            )
            await self.session.commit()
            return AssetRead.model_validate(asset)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- categories ----

    async def list_categories(self) -> Sequence[AssetCategoryRead]:
        rows = (
            await self.session.scalars(
                organization_query(AssetCategory, self.actor.organization_id).order_by(
                    AssetCategory.name
                )
            )
        ).all()
        return [AssetCategoryRead.model_validate(row) for row in rows]

    async def create_category(self, body: AssetCategoryCreate) -> AssetCategoryRead:
        try:
            if body.parent_category_id is not None:
                parent = (
                    await self.session.scalars(
                        select(AssetCategory).where(
                            AssetCategory.id == body.parent_category_id,
                            AssetCategory.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if parent is None:
                    raise NotFoundError("Parent category not found")
            category = AssetCategory(
                organization_id=self.actor.organization_id,
                name=body.name,
                description=body.description,
                parent_category_id=body.parent_category_id,
            )
            self.session.add(category)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset_category.created",
                entity_type="asset_category",
                entity_id=category.id,
                new_values={"name": body.name},
            )
            await self.session.commit()
            return AssetCategoryRead.model_validate(category)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- components ----

    async def list_components(self, asset_id: uuid.UUID) -> Sequence[AssetComponentRead]:
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetComponent, self.actor.organization_id)
                .where(AssetComponent.asset_id == asset_id)
                .order_by(AssetComponent.created_at)
            )
        ).all()
        return [AssetComponentRead.model_validate(row) for row in rows]

    async def add_component(
        self, asset_id: uuid.UUID, body: AssetComponentCreate
    ) -> AssetComponentRead:
        try:
            await self._get_or_404(asset_id)
            component = AssetComponent(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                name=body.name,
                component_type=body.component_type,
                manufacturer=body.manufacturer,
                model=body.model,
                serial_number=body.serial_number,
                installation_date=body.installation_date,
                meter_at_installation=body.meter_at_installation,
                expected_life_hours=body.expected_life_hours,
                status=body.status,
                notes=body.notes,
            )
            self.session.add(component)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.component_added",
                entity_type="asset_component",
                entity_id=component.id,
                new_values={"asset_id": str(asset_id), "name": body.name},
            )
            await self.session.commit()
            return AssetComponentRead.model_validate(component)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- documents ----

    async def list_documents(self, asset_id: uuid.UUID) -> Sequence[AssetDocumentRead]:
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetDocument, self.actor.organization_id)
                .where(AssetDocument.asset_id == asset_id)
                .order_by(AssetDocument.created_at)
            )
        ).all()
        return [AssetDocumentRead.model_validate(row) for row in rows]

    async def add_document(
        self,
        asset_id: uuid.UUID,
        body: AssetDocumentCreate,
        request: Request | None = None,
    ) -> AssetDocumentRead:
        try:
            await self._get_or_404(asset_id)
            if body.expiry_date and body.issue_date and body.expiry_date < body.issue_date:
                raise ValidationError("Document expiry cannot precede issue date")
            document = AssetDocument(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                document_type=body.document_type,
                title=body.title,
                document_number=body.document_number,
                file_url=str(body.file_url),
                file_name=body.file_name,
                mime_type=body.mime_type,
                issue_date=body.issue_date,
                expiry_date=body.expiry_date,
                issuing_authority=body.issuing_authority,
                notes=body.notes,
                created_by_id=self.actor.id,
            )
            self.session.add(document)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="document.added",
                entity_type="asset_document",
                entity_id=document.id,
                new_values={"asset_id": str(asset_id), "title": body.title},
                **_meta(request),
            )
            await self.session.commit()
            return AssetDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def upload_document(
        self,
        asset_id: uuid.UUID,
        data: bytes,
        filename: str | None,
        content_type: str | None,
        storage: LocalStorage,
        document_type: DocumentType = DocumentType.OTHER,
        title: str | None = None,
        document_number: str | None = None,
        issue_date: date | None = None,
        expiry_date: date | None = None,
        issuing_authority: str | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ) -> AssetDocumentRead:
        try:
            await self._get_or_404(asset_id)
            if expiry_date and issue_date and expiry_date < issue_date:
                raise ValidationError("Document expiry cannot precede issue date")
            resolved_title = title or (filename or "Untitled document")
            if len(resolved_title) > 200:
                raise ValidationError("Document title must be at most 200 characters")
            try:
                stored = await run_in_threadpool(
                    storage.save,
                    f"asset-documents/{asset_id}",
                    data,
                    filename or "upload.bin",
                    content_type,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            document = AssetDocument(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                document_type=document_type,
                title=resolved_title,
                document_number=document_number,
                file_url="pending",
                storage_path=stored.relative_path,
                file_name=stored.filename,
                mime_type=stored.mime_type,
                issue_date=issue_date,
                expiry_date=expiry_date,
                issuing_authority=issuing_authority,
                notes=notes,
                created_by_id=self.actor.id,
            )
            self.session.add(document)
            await self.session.flush()
            document.file_url = f"/api/v1/assets/{asset_id}/documents/{document.id}/download"
            document.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="document.added",
                entity_type="asset_document",
                entity_id=document.id,
                new_values={
                    "asset_id": str(asset_id),
                    "title": document.title,
                    "file_name": stored.filename,
                    "size_bytes": stored.size_bytes,
                },
                **_meta(request),
            )
            await self.session.commit()
            return AssetDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def download_document(
        self,
        asset_id: uuid.UUID,
        document_id: uuid.UUID,
        storage: LocalStorage,
    ) -> tuple[Path, str, str]:
        await self._get_or_404(asset_id)
        document = (
            await self.session.scalars(
                organization_query(AssetDocument, self.actor.organization_id).where(
                    AssetDocument.id == document_id,
                    AssetDocument.asset_id == asset_id,
                )
            )
        ).one_or_none()
        if document is None:
            raise NotFoundError("Document not found")
        if not document.storage_path:
            raise NotFoundError("No stored file for this document")
        try:
            path = await run_in_threadpool(storage.resolve, document.storage_path)
            exists = await run_in_threadpool(path.is_file)
        except ValueError:
            raise NotFoundError("Stored file is unavailable") from None
        if not exists:
            raise NotFoundError("Stored file is missing")
        return (
            path,
            document.mime_type or "application/octet-stream",
            document.file_name or document.title,
        )

    # ---- assignments ----

    async def list_assignments(self, asset_id: uuid.UUID) -> Sequence[AssetAssignmentRead]:
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetAssignment, self.actor.organization_id)
                .where(AssetAssignment.asset_id == asset_id)
                .order_by(AssetAssignment.assigned_at.desc())
            )
        ).all()
        return [AssetAssignmentRead.model_validate(row) for row in rows]

    async def create_assignment(
        self,
        asset_id: uuid.UUID,
        body: AssetAssignmentCreate,
        request: Request | None = None,
    ) -> AssetAssignmentRead:
        try:
            asset = await self._get_or_404(asset_id)
            if not asset.is_active or asset.archived_at is not None:
                raise ConflictError("Cannot assign an archived or inactive asset")
            project = (
                await self.session.scalars(
                    select(Project).where(
                        Project.id == body.project_id,
                        Project.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if project is None:
                raise NotFoundError("Project not found")
            if body.location_id is not None:
                location = (
                    await self.session.scalars(
                        select(Location).where(
                            Location.id == body.location_id,
                            Location.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if location is None:
                    raise NotFoundError("Location not found")
                if location.project_id is not None and location.project_id != project.id:
                    raise ValidationError("Location does not belong to the given project")
            if body.responsible_employee_id is not None:
                employee = (
                    await self.session.scalars(
                        select(Employee).where(
                            Employee.id == body.responsible_employee_id,
                            Employee.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if employee is None:
                    raise NotFoundError("Responsible employee not found")
            if body.status == AssignmentStatus.ACTIVE:
                conflict = (
                    await self.session.scalars(
                        organization_query(AssetAssignment, self.actor.organization_id).where(
                            AssetAssignment.asset_id == asset_id,
                            AssetAssignment.status == AssignmentStatus.ACTIVE,
                        )
                    )
                ).first()
                if conflict is not None:
                    raise ConflictError("Asset already has an active assignment; return it first")
            number = await next_business_number(
                self.session, self.actor.organization_id, "assignment"
            )
            assignment = AssetAssignment(
                organization_id=self.actor.organization_id,
                assignment_number=number,
                asset_id=asset_id,
                project_id=body.project_id,
                location_id=body.location_id,
                responsible_employee_id=body.responsible_employee_id,
                assigned_at=body.assigned_at,
                starting_meter=body.starting_meter,
                status=body.status,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(assignment)
            if body.responsible_employee_id is not None:
                asset.responsible_employee_id = body.responsible_employee_id
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.assigned",
                entity_type="asset_assignment",
                entity_id=assignment.id,
                new_values={
                    "assignment_number": number,
                    "asset_id": str(asset_id),
                    "project_id": str(body.project_id),
                },
                **_meta(request),
            )
            await self.session.commit()
            return AssetAssignmentRead.model_validate(assignment)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update_assignment(
        self,
        assignment_id: uuid.UUID,
        body: AssetAssignmentUpdate,
        request: Request | None = None,
    ) -> AssetAssignmentRead:
        try:
            assignment = (
                await self.session.scalars(
                    organization_query(AssetAssignment, self.actor.organization_id).where(
                        AssetAssignment.id == assignment_id
                    )
                )
            ).one_or_none()
            if assignment is None:
                raise NotFoundError("Assignment not found")
            data = body.model_dump(exclude_unset=True)
            if data.get("location_id") is not None:
                location = (
                    await self.session.scalars(
                        select(Location).where(
                            Location.id == data["location_id"],
                            Location.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if location is None:
                    raise NotFoundError("Location not found")
                if location.project_id is not None and location.project_id != assignment.project_id:
                    raise ValidationError("Location does not belong to the assignment project")
            if data.get("responsible_employee_id") is not None:
                employee = (
                    await self.session.scalars(
                        select(Employee).where(
                            Employee.id == data["responsible_employee_id"],
                            Employee.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if employee is None:
                    raise NotFoundError("Responsible employee not found")
            assigned_at = assignment.assigned_at
            returned_at = data.get("returned_at", assignment.returned_at)
            if returned_at is not None and returned_at < assigned_at:
                raise ValidationError("Return time cannot precede assignment time")
            new_status = data.get("status", assignment.status)
            if (
                new_status == AssignmentStatus.ACTIVE
                and assignment.status != AssignmentStatus.ACTIVE
            ):
                conflict = (
                    await self.session.scalars(
                        organization_query(AssetAssignment, self.actor.organization_id).where(
                            AssetAssignment.asset_id == assignment.asset_id,
                            AssetAssignment.status == AssignmentStatus.ACTIVE,
                            AssetAssignment.id != assignment.id,
                        )
                    )
                ).first()
                if conflict is not None:
                    raise ConflictError("Asset already has an active assignment")
            if new_status == AssignmentStatus.COMPLETED and returned_at is None:
                data["returned_at"] = datetime.now(UTC)
            for key, value in data.items():
                setattr(assignment, key, value)
            assignment.updated_by_id = self.actor.id
            assignment.updated_at = datetime.now(UTC)
            returned = new_status == AssignmentStatus.COMPLETED
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.returned" if returned else "asset.assignment_updated",
                entity_type="asset_assignment",
                entity_id=assignment.id,
                new_values={"status": str(new_status)},
                **_meta(request),
            )
            await self.session.commit()
            return AssetAssignmentRead.model_validate(assignment)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- meter readings ----

    async def list_meter_readings(self, asset_id: uuid.UUID) -> Sequence[AssetMeterReadingRead]:
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetMeterReading, self.actor.organization_id)
                .where(AssetMeterReading.asset_id == asset_id)
                .order_by(AssetMeterReading.recorded_at.desc())
            )
        ).all()
        return [AssetMeterReadingRead.model_validate(row) for row in rows]

    async def record_meter_reading(
        self,
        asset_id: uuid.UUID,
        body: AssetMeterReadingCreate,
        request: Request | None = None,
    ) -> AssetMeterReadingRead:
        try:
            asset = await self._get_or_404(asset_id)
            if body.project_id is not None:
                project = (
                    await self.session.scalars(
                        select(Project).where(
                            Project.id == body.project_id,
                            Project.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if project is None:
                    raise NotFoundError("Project not found")
            if body.location_id is not None:
                location = (
                    await self.session.scalars(
                        select(Location).where(
                            Location.id == body.location_id,
                            Location.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if location is None:
                    raise NotFoundError("Location not found")
            previous = (
                await self.session.scalars(
                    organization_query(AssetMeterReading, self.actor.organization_id)
                    .where(
                        AssetMeterReading.asset_id == asset_id,
                        AssetMeterReading.reading_type == body.reading_type,
                    )
                    .order_by(AssetMeterReading.recorded_at.desc())
                    .limit(1)
                )
            ).first()
            if previous is not None and body.reading < previous.reading and not body.is_correction:
                raise ValidationError(
                    "Meter reading cannot decrease; resubmit as a correction with a reason"
                )
            if body.is_correction and not body.notes:
                raise ValidationError("Corrections require a reason in notes")
            reading = AssetMeterReading(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                reading=body.reading,
                recorded_at=body.recorded_at,
                reading_type=body.reading_type,
                source=body.source,
                project_id=body.project_id,
                location_id=body.location_id,
                recorded_by_id=self.actor.id,
                notes=body.notes,
                created_at=datetime.now(UTC),
            )
            self.session.add(reading)
            asset.current_meter_reading = body.reading
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.meter_recorded",
                entity_type="asset_meter_reading",
                entity_id=reading.id,
                new_values={
                    "asset_id": str(asset_id),
                    "reading": str(body.reading),
                    "reading_type": str(body.reading_type),
                },
                **_meta(request),
            )
            await self.session.commit()
            return AssetMeterReadingRead.model_validate(reading)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- overview ----

    async def overview(self, asset_id: uuid.UUID) -> Any:
        asset = await self._get_or_404(asset_id)
        category = (
            await self.session.scalars(
                select(AssetCategory).where(
                    AssetCategory.id == asset.category_id,
                    AssetCategory.organization_id == self.actor.organization_id,
                )
            )
        ).one_or_none()
        assignments = await self.list_assignments(asset_id)
        current = next((a for a in assignments if a.status == AssignmentStatus.ACTIVE), None)
        current_location = None
        location_id = (
            current.location_id if current and current.location_id else (asset.default_location_id)
        )
        if location_id is not None:
            loc = (
                await self.session.scalars(
                    select(Location).where(
                        Location.id == location_id,
                        Location.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if loc is not None:
                current_location = LocationRead.model_validate(loc)
        responsible = None
        responsible_id = (
            current.responsible_employee_id
            if current and current.responsible_employee_id
            else asset.responsible_employee_id
        )
        if responsible_id is not None:
            emp = (
                await self.session.scalars(
                    select(Employee).where(
                        Employee.id == responsible_id,
                        Employee.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if emp is not None:
                responsible = EmployeeRead.model_validate(emp)
        readings = await self.list_meter_readings(asset_id)
        components = await self.list_components(asset_id)
        documents = await self.list_documents(asset_id)
        from app.schemas.asset import AssetCategoryRead as CategoryRead

        return AssetOverview(
            asset=AssetRead.model_validate(asset),
            category=CategoryRead.model_validate(category) if category else None,
            current_assignment=current,
            current_location=current_location,
            responsible_employee=responsible,
            latest_meter_reading=readings[0] if readings else None,
            recent_assignments=assignments[:10],
            components=components,
            documents=list(documents),
        )

    # ---- location history ----

    async def list_location_history(self, asset_id: uuid.UUID) -> Sequence:
        """List location change history for an asset"""
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetLocationHistory, self.actor.organization_id)
                .where(AssetLocationHistory.asset_id == asset_id)
                .order_by(AssetLocationHistory.recorded_at.desc())
            )
        ).all()
        return rows

    async def record_location_event(
        self,
        asset_id: uuid.UUID,
        location_id: uuid.UUID,
        event_type: str,
        project_id: uuid.UUID | None = None,
        meter_reading: decimal.Decimal | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Record a location change event for an asset"""
        try:
            await self._get_or_404(asset_id)
            location = (
                await self.session.scalars(
                    select(Location).where(
                        Location.id == location_id,
                        Location.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if location is None:
                raise NotFoundError("Location not found")
            
            event = AssetLocationHistory(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                location_id=location_id,
                project_id=project_id,
                event_type=event_type,
                recorded_at=datetime.now(UTC),
                meter_reading=meter_reading,
                recorded_by_id=self.actor.id,
                notes=notes,
            )
            self.session.add(event)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.location_changed",
                entity_type="asset_location_history",
                entity_id=event.id,
                new_values={"asset_id": str(asset_id), "event_type": event_type, "location_id": str(location_id)},
                **_meta(request),
            )
            await self.session.commit()
            return event
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- status history ----

    async def change_status(
        self,
        asset_id: uuid.UUID,
        new_status: str,
        reason: str | None = None,
        request: Request | None = None,
    ):
        """Change asset operational status and record history"""
        try:
            asset = await self._get_or_404(asset_id)
            old_status = asset.status
            
            asset.status = new_status
            asset.updated_by_id = self.actor.id
            asset.updated_at = datetime.now(UTC)
            
            history = AssetStatusHistory(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                previous_status=str(old_status),
                new_status=new_status,
                changed_at=datetime.now(UTC),
                changed_by_id=self.actor.id,
                reason=reason,
            )
            self.session.add(history)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.status_changed",
                entity_type="asset_status_history",
                entity_id=history.id,
                new_values={"asset_id": str(asset_id), "old_status": str(old_status), "new_status": new_status},
                **_meta(request),
            )
            await self.session.commit()
            return AssetRead.model_validate(asset)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- insurance ----

    async def list_insurance(self, asset_id: uuid.UUID):
        """List insurance records for an asset"""
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetInsurance, self.actor.organization_id)
                .where(AssetInsurance.asset_id == asset_id)
                .order_by(AssetInsurance.expiry_date)
            )
        ).all()
        return rows

    async def add_insurance(
        self,
        asset_id: uuid.UUID,
        provider: str,
        policy_number: str,
        start_date: date,
        expiry_date: date,
        coverage_type: str | None = None,
        coverage_amount: decimal.Decimal | None = None,
        currency: str | None = None,
        premium_amount: decimal.Decimal | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Add insurance record for an asset"""
        try:
            await self._get_or_404(asset_id)
            if expiry_date < start_date:
                raise ValidationError("Expiry date cannot precede start date")
            
            insurance = AssetInsurance(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                provider=provider,
                policy_number=policy_number,
                coverage_type=coverage_type,
                coverage_amount=coverage_amount,
                currency=currency,
                start_date=start_date,
                expiry_date=expiry_date,
                premium_amount=premium_amount,
                status="ACTIVE",
                notes=notes,
            )
            self.session.add(insurance)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.insurance_added",
                entity_type="asset_insurance",
                entity_id=insurance.id,
                new_values={"asset_id": str(asset_id), "provider": provider, "policy_number": policy_number},
                **_meta(request),
            )
            await self.session.commit()
            return insurance
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_expiring_insurance(self, days: int = 30) -> Sequence:
        """Get insurance records expiring within N days"""
        from datetime import timedelta
        cutoff_date = (datetime.now(UTC) + timedelta(days=days)).date()
        rows = (
            await self.session.scalars(
                organization_query(AssetInsurance, self.actor.organization_id)
                .where(
                    AssetInsurance.expiry_date <= cutoff_date,
                    AssetInsurance.expiry_date >= datetime.now(UTC).date(),
                    AssetInsurance.status == "ACTIVE",
                )
                .order_by(AssetInsurance.expiry_date)
            )
        ).all()
        return rows

    # ---- registration ----

    async def list_registrations(self, asset_id: uuid.UUID):
        """List registration records for an asset"""
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetRegistration, self.actor.organization_id)
                .where(AssetRegistration.asset_id == asset_id)
                .order_by(AssetRegistration.expiry_date.desc())
            )
        ).all()
        return rows

    async def add_registration(
        self,
        asset_id: uuid.UUID,
        registration_type: str,
        registration_number: str,
        issuing_authority: str | None = None,
        issue_date: date | None = None,
        expiry_date: date | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Add registration record for an asset"""
        try:
            await self._get_or_404(asset_id)
            if expiry_date and issue_date and expiry_date < issue_date:
                raise ValidationError("Expiry date cannot precede issue date")
            
            registration = AssetRegistration(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                registration_type=registration_type,
                registration_number=registration_number,
                issuing_authority=issuing_authority,
                issue_date=issue_date,
                expiry_date=expiry_date,
                status="ACTIVE",
                notes=notes,
            )
            self.session.add(registration)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.registration_added",
                entity_type="asset_registration",
                entity_id=registration.id,
                new_values={"asset_id": str(asset_id), "type": registration_type, "number": registration_number},
                **_meta(request),
            )
            await self.session.commit()
            return registration
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_expiring_registrations(self, days: int = 30) -> Sequence:
        """Get registrations expiring within N days"""
        from datetime import timedelta
        cutoff_date = (datetime.now(UTC) + timedelta(days=days)).date()
        rows = (
            await self.session.scalars(
                organization_query(AssetRegistration, self.actor.organization_id)
                .where(
                    AssetRegistration.expiry_date <= cutoff_date,
                    AssetRegistration.expiry_date >= datetime.now(UTC).date(),
                    AssetRegistration.status == "ACTIVE",
                )
                .order_by(AssetRegistration.expiry_date)
            )
        ).all()
        return rows

    # ---- inspections ----

    async def list_inspections(
        self,
        asset_id: uuid.UUID,
        inspection_type: str | None = None,
        condition_status: str | None = None,
    ) -> Sequence:
        """List inspections for an asset with optional filters"""
        await self._get_or_404(asset_id)
        query = organization_query(AssetInspection, self.actor.organization_id).where(
            AssetInspection.asset_id == asset_id
        )
        if inspection_type:
            query = query.where(AssetInspection.inspection_type == inspection_type)
        if condition_status:
            query = query.where(AssetInspection.condition_status == condition_status)
        rows = (
            await self.session.scalars(
                query.order_by(AssetInspection.inspection_date.desc())
            )
        ).all()
        return rows

    async def create_inspection(
        self,
        asset_id: uuid.UUID,
        inspection_type: str,
        condition_status: str,
        project_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        meter_reading: decimal.Decimal | None = None,
        summary: str | None = None,
        defects_found: bool = False,
        defect_notes: str | None = None,
        follow_up_required: bool = False,
        request: Request | None = None,
    ):
        """Create an inspection record for an asset"""
        try:
            await self._get_or_404(asset_id)
            
            inspection = AssetInspection(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                inspection_type=inspection_type,
                inspection_date=datetime.now(UTC),
                project_id=project_id,
                location_id=location_id,
                inspected_by_id=self.actor.id,
                meter_reading=meter_reading,
                condition_status=condition_status,
                summary=summary,
                defects_found=defects_found,
                defect_notes=defect_notes,
                follow_up_required=follow_up_required,
            )
            self.session.add(inspection)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.inspection_created",
                entity_type="asset_inspection",
                entity_id=inspection.id,
                new_values={"asset_id": str(asset_id), "type": inspection_type, "status": condition_status},
                **_meta(request),
            )
            await self.session.commit()
            return inspection
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- defects ----

    async def list_defects(
        self,
        asset_id: uuid.UUID,
        status: str | None = None,
        severity: str | None = None,
    ) -> Sequence:
        """List defects for an asset with optional filters"""
        await self._get_or_404(asset_id)
        query = organization_query(AssetDefect, self.actor.organization_id).where(
            AssetDefect.asset_id == asset_id
        )
        if status:
            query = query.where(AssetDefect.status == status)
        if severity:
            query = query.where(AssetDefect.severity == severity)
        rows = (
            await self.session.scalars(
                query.order_by(AssetDefect.reported_at.desc())
            )
        ).all()
        return rows

    async def report_defect(
        self,
        asset_id: uuid.UUID,
        severity: str,
        description: str,
        inspection_id: uuid.UUID | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Report a new defect for an asset"""
        try:
            await self._get_or_404(asset_id)
            
            defect = AssetDefect(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                inspection_id=inspection_id,
                reported_at=datetime.now(UTC),
                reported_by_id=self.actor.id,
                severity=severity,
                description=description,
                status="OPEN",
                notes=notes,
            )
            self.session.add(defect)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.defect_reported",
                entity_type="asset_defect",
                entity_id=defect.id,
                new_values={"asset_id": str(asset_id), "severity": severity},
                **_meta(request),
            )
            await self.session.commit()
            return defect
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def resolve_defect(
        self,
        defect_id: uuid.UUID,
        asset_id: uuid.UUID,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Resolve/close a defect"""
        try:
            await self._get_or_404(asset_id)
            defect = (
                await self.session.scalars(
                    organization_query(AssetDefect, self.actor.organization_id).where(
                        AssetDefect.id == defect_id,
                        AssetDefect.asset_id == asset_id,
                    )
                )
            ).one_or_none()
            if defect is None:
                raise NotFoundError("Defect not found")
            
            defect.status = "RESOLVED"
            defect.resolved_at = datetime.now(UTC)
            if notes:
                defect.notes = notes
            
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.defect_resolved",
                entity_type="asset_defect",
                entity_id=defect.id,
                new_values={"asset_id": str(asset_id), "status": "RESOLVED"},
                **_meta(request),
            )
            await self.session.commit()
            return defect
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_critical_defects(self) -> Sequence:
        """Get all open critical defects in the organization"""
        rows = (
            await self.session.scalars(
                organization_query(AssetDefect, self.actor.organization_id)
                .where(
                    AssetDefect.severity == "CRITICAL",
                    AssetDefect.status == "OPEN",
                )
                .order_by(AssetDefect.reported_at.desc())
            )
        ).all()
        return rows
