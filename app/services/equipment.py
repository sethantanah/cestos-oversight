"""Asset lifecycle services, sharing existing asset IDs, counters and storage."""

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from fastapi import Request
from sqlalchemy import func, inspect, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import scoped_roles
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetComponent,
    AssetDocument,
    AssetMeterReading,
    Employee,
    Location,
    Project,
    User,
)
from app.models.asset import AssetStatus, ComponentStatus, MeterType, ReadingType
from app.models.asset_records import (
    AssetDefect,
    AssetInspection,
    AssetInsurance,
    AssetLocationHistory,
    AssetMedia,
    AssetOwnership,
    AssetRegistration,
    AssetStatusHistory,
)
from app.models.audit_log import AuditLog
from app.models.employee import AssignmentStatus
from app.schemas.asset import (
    AssetAssignmentRead,
    AssetCategoryRead,
    AssetComponentRead,
    AssetMeterReadingRead,
    AssetRead,
)
from app.services.assets import AssetService as ExistingAssetService
from app.services.audit import record_audit
from app.services.counters import next_business_number

METER_STALE_DAYS = 7
RECORDS = {
    "insurance": AssetInsurance,
    "registrations": AssetRegistration,
    "ownership": AssetOwnership,
    "media": AssetMedia,
    "inspections": AssetInspection,
    "defects": AssetDefect,
    "location-history": AssetLocationHistory,
    "status-history": AssetStatusHistory,
}
FINANCIAL = {
    "purchase_price",
    "purchase_currency",
    "residual_value",
    "coverage_amount",
    "premium_amount",
    "amount",
}


class EquipmentService(ExistingAssetService):
    def permitted(self, code: str) -> bool:
        aliases = {
            "assets.meter.record": "assets.record_meter",
            "assets.documents.read": "asset_documents.read",
            "assets.documents.manage": "asset_documents.manage",
        }
        return self.actor.is_superuser or any(
            p.code in {code, aliases.get(code, code)}
            for r in scoped_roles(self.actor)
            for p in r.permissions
        )

    def require(self, code: str) -> None:
        if not self.permitted(code):
            raise ForbiddenError("Required permission is missing")

    async def ref(
        self,
        model: Any,
        identifier: uuid.UUID | None,
        asset_id: uuid.UUID | None = None,
        lock: bool = False,
    ) -> Any:
        if identifier is None:
            return None
        query = select(model).where(
            model.id == identifier, model.organization_id == self.actor.organization_id
        )
        if asset_id is not None:
            query = query.where(model.asset_id == asset_id)
        if lock:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        if row is None:
            raise NotFoundError("Related record not found")
        return row

    async def asset(self, identifier: uuid.UUID, lock: bool = False) -> Asset:
        return cast(Asset, await self.ref(Asset, identifier, lock=lock))

    def audit(
        self,
        action: str,
        asset_id: uuid.UUID,
        record: Any = None,
        values: dict[str, Any] | None = None,
    ) -> None:
        record_audit(
            self.session,
            organization_id=self.actor.organization_id,
            actor_user_id=self.actor.id,
            action=action,
            entity_type="asset" if record is None else record.__tablename__,
            entity_id=asset_id if record is None else record.id,
            new_values={"asset_id": str(asset_id), **(values or {})},
        )

    async def commit(self) -> None:
        try:
            await self.session.flush()
            for obj in list(self.session.identity_map.values()):
                expired = cast(Any, inspect(obj)).expired_attributes
                if expired:
                    await self.session.refresh(obj, attribute_names=list(expired))
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError(
                "Record conflicts with existing data or required constraints"
            ) from error

    def public(self, row: Any) -> dict[str, Any]:
        data = {
            c.key: getattr(row, c.key)
            for c in inspect(type(row)).columns
            if c.key != "storage_path"
        }
        if not self.permitted("assets.financial.read"):
            for key in FINANCIAL:
                data.pop(key, None)
        return data

    def read_asset(self, row: Asset) -> AssetRead:
        result = AssetRead.model_validate(row)
        if not self.permitted("assets.financial.read"):
            result.purchase_price = None
            result.purchase_currency = None
            result.residual_value = None
        return result

    async def get(self, asset_id: uuid.UUID) -> AssetRead:
        return self.read_asset(await self.asset(asset_id))

    async def validate_fields(
        self, data: dict[str, Any], asset_id: uuid.UUID | None = None
    ) -> None:
        refs = {
            "category_id": AssetCategory,
            "parent_category_id": AssetCategory,
            "project_id": Project,
            "location_id": Location,
            "default_location_id": Location,
            "responsible_employee_id": Employee,
            "primary_operator_id": Employee,
            "inspected_by_id": User,
            "document_id": AssetDocument,
            "inspection_id": AssetInspection,
            "parent_component_id": AssetComponent,
        }
        for key, model in refs.items():
            if data.get(key) is not None:
                await self.ref(
                    model,
                    data[key],
                    asset_id
                    if key in {"document_id", "inspection_id", "parent_component_id"}
                    else None,
                )
        for start, end in [
            ("warranty_start_date", "warranty_expiry_date"),
            ("start_date", "expiry_date"),
            ("issue_date", "expiry_date"),
            ("start_date", "end_date"),
            ("installation_date", "removal_date"),
            ("assigned_at", "expected_return_at"),
            ("assigned_at", "returned_at"),
        ]:
            if data.get(start) and data.get(end) and data[end] < data[start]:
                raise ValidationError(f"{end} cannot precede {start}")
        for key, value in data.items():
            if isinstance(value, datetime) and value.utcoffset() is None:
                raise ValidationError(f"{key} requires a timezone")
        if data.get("location_id") and data.get("project_id"):
            loc = await self.ref(Location, data["location_id"])
            if loc.project_id and loc.project_id != data["project_id"]:
                raise ValidationError("Location does not belong to the selected project")

    async def create_category(self, body: Any) -> AssetCategoryRead:
        await self.validate_fields(body.model_dump())
        row = AssetCategory(
            organization_id=self.actor.organization_id,
            created_by_id=self.actor.id,
            updated_by_id=self.actor.id,
            **body.model_dump(),
        )
        self.session.add(row)
        await self.session.flush()
        self.audit("asset_category.created", row.id)
        await self.commit()
        return AssetCategoryRead.model_validate(row)

    async def update_category(self, identifier: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
        row = await self.ref(AssetCategory, identifier, lock=True)
        await self.validate_fields(data)
        parent = data.get("parent_category_id")
        seen = {identifier}
        while parent:
            if parent in seen:
                raise ValidationError("Category hierarchy cannot contain cycles")
            seen.add(parent)
            parent = (await self.ref(AssetCategory, parent)).parent_category_id
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_by_id = self.actor.id
        self.audit("asset_category.updated", row.id)
        await self.commit()
        return self.public(row)

    async def create(self, body: Any, request: Request | None = None) -> AssetRead:
        data = body.model_dump()
        await self.validate_fields(data)
        category = await self.ref(AssetCategory, body.category_id)
        if not category.is_active:
            raise ValidationError("Choose an active category")
        if "meter_type" not in body.model_fields_set and category.default_meter_type:
            data["meter_type"] = category.default_meter_type
        row = Asset(
            organization_id=self.actor.organization_id,
            asset_number=await next_business_number(
                self.session, self.actor.organization_id, "asset"
            ),
            created_by_id=self.actor.id,
            updated_by_id=self.actor.id,
            **data,
        )
        self.session.add(row)
        await self.session.flush()
        row.qr_code_value = row.qr_code_value or row.asset_number
        self.status_event(row, None, row.status, "Asset registered")
        if row.default_location_id:
            self.location_event(row, row.default_location_id, "MANUAL_UPDATE", datetime.now(UTC))
        if row.current_meter_reading is not None and row.meter_type != MeterType.NONE:
            self.session.add(
                AssetMeterReading(
                    organization_id=self.actor.organization_id,
                    asset_id=row.id,
                    reading=row.current_meter_reading,
                    reading_type=ReadingType(row.meter_type.value),
                    recorded_at=datetime.now(UTC),
                    recorded_by_id=self.actor.id,
                    source="IMPORT",
                )
            )
        self.session.add(
            AssetOwnership(
                organization_id=self.actor.organization_id,
                asset_id=row.id,
                ownership_type=row.ownership_type.value,
                owner_or_provider=row.ownership_entity or "Not recorded",
                start_date=row.purchase_date or date.today(),
                amount=row.purchase_price,
                currency=row.purchase_currency,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
        )
        self.audit("asset.created", row.id, values={"asset_number": row.asset_number})
        await self.commit()
        return self.read_asset(row)

    def status_event(self, asset: Asset, previous: Any, new: Any, reason: str) -> None:
        self.session.add(
            AssetStatusHistory(
                organization_id=self.actor.organization_id,
                asset_id=asset.id,
                previous_status=previous,
                new_status=new,
                changed_at=datetime.now(UTC),
                changed_by_id=self.actor.id,
                reason=reason,
            )
        )
        asset.status = new
        self.audit(
            "asset.status_changed",
            asset.id,
            values={"previous_status": previous, "new_status": new, "reason": reason},
        )

    def location_event(
        self,
        asset: Asset,
        location_id: uuid.UUID,
        event_type: str,
        when: datetime,
        assignment: AssetAssignment | None = None,
    ) -> None:
        self.session.add(
            AssetLocationHistory(
                organization_id=self.actor.organization_id,
                asset_id=asset.id,
                location_id=location_id,
                event_type=event_type,
                recorded_at=when,
                project_id=assignment.project_id if assignment else None,
                recorded_by_id=self.actor.id,
                source_reference_type="asset_assignment" if assignment else None,
                source_reference_id=assignment.id if assignment else None,
            )
        )
        self.audit(
            "asset.location_changed",
            asset.id,
            values={"location_id": str(location_id), "event_type": event_type},
        )

    def validate_transition(self, asset: Asset, new: AssetStatus) -> None:
        if asset.status == AssetStatus.DISPOSED and new != asset.status:
            raise ConflictError("Disposed equipment cannot return to operation")
        if asset.status in {
            AssetStatus.OUT_OF_SERVICE,
            AssetStatus.QUARANTINED,
            AssetStatus.LOST,
            AssetStatus.STOLEN,
        } and new in {AssetStatus.OPERATING, AssetStatus.AVAILABLE, AssetStatus.ASSIGNED}:
            self.require("assets.status.override")

    async def update(
        self, asset_id: uuid.UUID, body: Any, request: Request | None = None
    ) -> AssetRead:
        row = await self.asset(asset_id, True)
        data = body.model_dump(exclude_unset=True)
        if "current_meter_reading" in data:
            raise ValidationError("Use meter readings or meter reset to preserve history")
        if "meter_type" in data and data["meter_type"] != row.meter_type:
            if await self.session.scalar(
                select(AssetMeterReading.id).where(AssetMeterReading.asset_id == row.id).limit(1)
            ):
                raise ConflictError("Meter type cannot change after readings exist")
        await self.validate_fields(
            {**{c.key: getattr(row, c.key) for c in inspect(Asset).columns}, **data}
        )
        if "status" in data:
            self.require("assets.status.change")
            self.validate_transition(row, data["status"])
            self.status_event(row, row.status, data.pop("status"), "Administrative update")
        if "is_active" in data:
            raise ValidationError("Use archive or restore")
        if "ownership_type" in data and data["ownership_type"] != row.ownership_type:
            raise ValidationError("Add ownership history to change ownership")
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_by_id = self.actor.id
        self.audit("asset.updated", row.id)
        await self.commit()
        return self.read_asset(row)

    async def change_status(
        self,
        asset_id: uuid.UUID,
        body: Any,
        reason: str | None = None,
        request: Request | None = None,
    ) -> AssetRead:
        if isinstance(body, str):
            from app.schemas.equipment import StatusChange

            body = StatusChange(new_status=AssetStatus(body), reason=reason or "Status changed")
        row = await self.asset(asset_id, True)
        self.validate_transition(row, body.new_status)
        self.status_event(row, row.status, body.new_status, body.reason)
        await self.commit()
        return self.read_asset(row)

    async def restore(self, asset_id: uuid.UUID) -> AssetRead:
        row = await self.asset(asset_id, True)
        row.is_active = True
        row.archived_at = None
        self.audit("asset.restored", row.id)
        await self.commit()
        return self.read_asset(row)

    async def archive(self, asset_id: uuid.UUID, request: Request | None = None) -> AssetRead:
        row = await self.asset(asset_id, True)
        if not row.is_active:
            raise ConflictError("Asset is already archived")
        if await self.active_assignment(asset_id):
            raise ConflictError("Complete the active assignment before archiving")
        row.is_active = False
        row.archived_at = datetime.now(UTC)
        self.audit("asset.archived", row.id)
        await self.commit()
        return self.read_asset(row)

    async def active_assignment(self, asset_id: uuid.UUID) -> AssetAssignment | None:
        return cast(
            AssetAssignment | None,
            await self.session.scalar(
                select(AssetAssignment).where(
                    AssetAssignment.organization_id == self.actor.organization_id,
                    AssetAssignment.asset_id == asset_id,
                    AssetAssignment.status == AssignmentStatus.ACTIVE,
                )
            ),
        )

    async def _assign(self, row: Asset, body: Any) -> AssetAssignment:
        data = body.model_dump(exclude={"ending_meter"})
        await self.validate_fields(data)
        if body.status not in {AssignmentStatus.ACTIVE, AssignmentStatus.PLANNED}:
            raise ValidationError("New assignments must be active or planned")
        project = await self.ref(Project, body.project_id)
        if not project.is_active or project.status in {"CLOSED", "COMPLETED", "CANCELLED"}:
            raise ConflictError("Cannot assign to a closed project")
        eligibility = await self.eligibility(row)
        if eligibility["operational_eligibility"] == "NOT_ELIGIBLE":
            raise ConflictError("Asset is not eligible: " + "; ".join(eligibility["reasons"]))
        if body.status == AssignmentStatus.ACTIVE and await self.active_assignment(row.id):
            raise ConflictError("Asset already has an active assignment")
        if (
            body.starting_meter is not None
            and row.current_meter_reading is not None
            and body.starting_meter < row.current_meter_reading
        ):
            raise ValidationError("Starting meter cannot decrease")
        assignment = AssetAssignment(
            organization_id=self.actor.organization_id,
            asset_id=row.id,
            assignment_number=await next_business_number(
                self.session, self.actor.organization_id, "assignment"
            ),
            created_by_id=self.actor.id,
            updated_by_id=self.actor.id,
            **data,
        )
        self.session.add(assignment)
        await self.session.flush()
        if body.status == AssignmentStatus.ACTIVE:
            self.status_event(row, row.status, AssetStatus.ASSIGNED, "Assignment started")
            if body.location_id:
                self.location_event(row, body.location_id, "ASSIGNED", body.assigned_at, assignment)
            if body.starting_meter is not None:
                await self.assignment_meter(
                    row, body.starting_meter, body.assigned_at, "ASSIGNMENT"
                )
        self.audit("asset.assigned", row.id, assignment)
        return assignment

    async def assignment_meter(
        self, row: Asset, value: Decimal, when: datetime, source: str
    ) -> None:
        if row.meter_type == MeterType.NONE:
            raise ValidationError("Asset has no meter")
        from app.schemas.asset import AssetMeterReadingCreate

        await self._meter(
            row,
            AssetMeterReadingCreate(
                reading=value,
                recorded_at=when,
                reading_type=ReadingType(row.meter_type.value),
                source=source,
            ),
        )

    async def create_assignment(
        self, asset_id: uuid.UUID, body: Any, request: Request | None = None
    ) -> AssetAssignmentRead:
        result = await self._assign(await self.asset(asset_id, True), body)
        await self.commit()
        return AssetAssignmentRead.model_validate(result)

    async def update_assignment(
        self, assignment_id: uuid.UUID, body: Any, request: Request | None = None
    ) -> AssetAssignmentRead:
        assignment = await self.ref(AssetAssignment, assignment_id)
        row = await self.asset(assignment.asset_id, True)
        await self.session.refresh(assignment)
        data = body.model_dump(exclude_unset=True)
        await self._finish_or_update(row, assignment, data)
        await self.commit()
        return AssetAssignmentRead.model_validate(assignment)

    async def _finish_or_update(
        self, row: Asset, assignment: AssetAssignment, data: dict[str, Any]
    ) -> None:
        if assignment.status in {AssignmentStatus.COMPLETED, AssignmentStatus.CANCELLED}:
            raise ConflictError("Completed or cancelled assignment history cannot be rewritten")
        new_status = data.get("status", assignment.status)
        if new_status == AssignmentStatus.COMPLETED:
            data.setdefault("returned_at", datetime.now(UTC))
        merged = {
            **{c.key: getattr(assignment, c.key) for c in inspect(AssetAssignment).columns},
            **data,
        }
        await self.validate_fields(merged)
        if (
            merged.get("ending_meter") is not None
            and merged.get("starting_meter") is not None
            and merged["ending_meter"] < merged["starting_meter"]
        ):
            raise ValidationError("Ending meter cannot precede starting meter")
        if (
            new_status == AssignmentStatus.ACTIVE
            and assignment.status != new_status
            and await self.active_assignment(row.id)
        ):
            raise ConflictError("Asset already has an active assignment")
        previous = assignment.status
        if new_status == AssignmentStatus.ACTIVE:
            project = await self.ref(Project, merged["project_id"])
            if not project.is_active or project.status in {"CLOSED", "COMPLETED", "CANCELLED"}:
                raise ConflictError("Cannot assign to a closed project")
            if previous != AssignmentStatus.ACTIVE:
                eligibility = await self.eligibility(row)
                if eligibility["operational_eligibility"] == "NOT_ELIGIBLE":
                    raise ConflictError(
                        "Asset is not eligible: " + "; ".join(eligibility["reasons"])
                    )
                self.status_event(row, row.status, AssetStatus.ASSIGNED, "Assignment started")
                if merged.get("location_id"):
                    self.location_event(
                        row, merged["location_id"], "ASSIGNED", merged["assigned_at"], assignment
                    )
                if merged.get("starting_meter") is not None:
                    await self.assignment_meter(
                        row, merged["starting_meter"], merged["assigned_at"], "ASSIGNMENT"
                    )
            elif any(key in data for key in ("project_id", "location_id")):
                raise ConflictError(
                    "Use transfer to change an active assignment's project or location"
                )
        for key, value in data.items():
            setattr(assignment, key, value)
        if (
            new_status in {AssignmentStatus.COMPLETED, AssignmentStatus.CANCELLED}
            and previous == AssignmentStatus.ACTIVE
        ):
            if row.status in {
                AssetStatus.ASSIGNED,
                AssetStatus.OPERATING,
                AssetStatus.MOBILIZING,
                AssetStatus.STANDBY,
            }:
                self.status_event(row, row.status, AssetStatus.AVAILABLE, "Assignment closed")
            if new_status == AssignmentStatus.COMPLETED and assignment.ending_meter is not None:
                await self.assignment_meter(
                    row,
                    assignment.ending_meter,
                    assignment.returned_at or datetime.now(UTC),
                    "RETURN",
                )
            if row.default_location_id:
                self.location_event(
                    row,
                    row.default_location_id,
                    "RETURNED_TO_YARD",
                    assignment.returned_at or datetime.now(UTC),
                )
        self.audit(
            "asset.assignment_completed"
            if new_status == AssignmentStatus.COMPLETED
            else "asset.assignment_updated",
            row.id,
            assignment,
        )

    async def transfer(self, asset_id: uuid.UUID, body: Any) -> AssetAssignmentRead:
        row = await self.asset(asset_id, True)
        current = await self.active_assignment(row.id)
        if not current:
            raise ConflictError("No active assignment to transfer")
        if body.status != AssignmentStatus.ACTIVE:
            raise ValidationError("Transfer must create an active assignment")
        if (
            body.starting_meter is not None
            and body.ending_meter is not None
            and body.starting_meter < body.ending_meter
        ):
            raise ValidationError("New starting meter cannot precede the return meter")
        await self._finish_or_update(
            row,
            current,
            {
                "status": AssignmentStatus.COMPLETED,
                "returned_at": body.assigned_at,
                "ending_meter": body.ending_meter,
            },
        )
        await self.session.flush()
        if body.starting_meter is None:
            body = body.model_copy(update={"starting_meter": body.ending_meter})
        assignment = await self._assign(row, body)
        if body.location_id:
            self.location_event(row, body.location_id, "TRANSFERRED", body.assigned_at, assignment)
        self.audit("asset.transferred", row.id, assignment)
        await self.commit()
        return AssetAssignmentRead.model_validate(assignment)

    async def _meter(self, row: Asset, body: Any) -> AssetMeterReading:
        await self.validate_fields(body.model_dump())
        if row.meter_type == MeterType.NONE:
            raise ValidationError("Asset has no meter")
        previous = await self.session.scalar(
            select(AssetMeterReading)
            .where(
                AssetMeterReading.asset_id == row.id,
                AssetMeterReading.organization_id == self.actor.organization_id,
                AssetMeterReading.reading_type == body.reading_type,
            )
            .order_by(AssetMeterReading.recorded_at.desc(), AssetMeterReading.created_at.desc())
            .limit(1)
        )
        adjustment = body.is_adjustment or body.is_correction
        reason = body.adjustment_reason or body.notes
        if adjustment:
            self.require("assets.meter.override")
            if not reason or not reason.strip():
                raise ValidationError("Meter adjustments require a reason")
        if previous and body.recorded_at < previous.recorded_at:
            raise ValidationError("Readings must follow the latest reading of this type")
        if previous and body.reading < previous.reading and not adjustment:
            raise ValidationError("Meter reading cannot decrease without an authorized adjustment")
        reading = AssetMeterReading(
            organization_id=self.actor.organization_id,
            asset_id=row.id,
            recorded_by_id=self.actor.id,
            previous_reading=previous.reading if previous else None,
            **body.model_dump(exclude={"is_correction", "is_adjustment", "adjustment_reason"}),
            is_adjustment=adjustment,
            adjustment_reason=reason if adjustment else None,
        )
        self.session.add(reading)
        if body.reading_type.value == row.meter_type.value:
            row.current_meter_reading = body.reading
        await self.session.flush()
        self.audit(
            "asset.meter_recorded",
            row.id,
            reading,
            {"reading": str(body.reading), "adjustment": adjustment},
        )
        return reading

    async def record_meter_reading(
        self, asset_id: uuid.UUID, body: Any, request: Request | None = None
    ) -> AssetMeterReadingRead:
        result = await self._meter(await self.asset(asset_id, True), body)
        await self.commit()
        return AssetMeterReadingRead.model_validate(result)

    async def reset_meter(self, asset_id: uuid.UUID, body: Any) -> AssetMeterReadingRead:
        self.require("assets.meter.override")
        row = await self.asset(asset_id, True)
        if row.current_meter_reading != body.old_reading:
            raise ConflictError("Old reading does not match the current meter")
        from app.schemas.asset import AssetMeterReadingCreate

        if row.meter_type == MeterType.NONE:
            raise ValidationError("Asset has no meter")
        result = await self._meter(
            row,
            AssetMeterReadingCreate(
                reading=body.new_reading,
                recorded_at=body.recorded_at,
                reading_type=ReadingType(row.meter_type.value),
                is_adjustment=True,
                adjustment_reason=body.reason,
                source="SERVICE",
            ),
        )
        result.meter_replaced = body.meter_replaced
        self.audit(
            "asset.meter_reset",
            row.id,
            result,
            {
                "old_reading": str(body.old_reading),
                "new_reading": str(body.new_reading),
                "reason": body.reason,
                "meter_replaced": body.meter_replaced,
            },
        )
        await self.commit()
        return AssetMeterReadingRead.model_validate(result)

    async def list_records(self, asset_id: uuid.UUID, kind: str) -> list[dict[str, Any]]:
        await self.asset(asset_id)
        model = RECORDS[kind]
        rows = (
            await self.session.scalars(
                select(model)
                .where(
                    model.organization_id == self.actor.organization_id, model.asset_id == asset_id
                )
                .order_by(model.created_at.desc(), model.id)
            )
        ).all()
        return [self.public(row) for row in rows]

    async def add_record(self, asset_id: uuid.UUID, kind: str, body: Any) -> dict[str, Any]:
        asset = await self.asset(asset_id, True)
        data = body.model_dump()
        await self.validate_fields(data, asset_id)
        if kind == "media":
            if not data["file_url"].startswith(("https://", "http://", "/api/v1/")):
                raise ValidationError("Use an HTTP URL or upload a file")
            data["uploaded_by_id"] = self.actor.id
            if data.get("is_primary"):
                await self.session.execute(
                    update(AssetMedia)
                    .where(
                        AssetMedia.asset_id == asset_id,
                        AssetMedia.organization_id == self.actor.organization_id,
                    )
                    .values(is_primary=False)
                )
                asset.profile_photo_url = data["file_url"]
        if kind == "inspections" and data.get("inspected_by_id") is None:
            data["inspected_by_id"] = self.actor.id
        if kind == "defects":
            data["reported_by_id"] = self.actor.id
        if kind == "ownership":
            current = (
                await self.session.scalars(
                    select(AssetOwnership).where(
                        AssetOwnership.asset_id == asset_id,
                        AssetOwnership.organization_id == self.actor.organization_id,
                        AssetOwnership.end_date.is_(None),
                    )
                )
            ).all()
            for previous in current:
                if data["start_date"] < previous.start_date:
                    raise ValidationError("New ownership cannot precede existing ownership")
                previous.end_date = data["start_date"]
            asset.ownership_type = data["ownership_type"]
            asset.ownership_entity = data["owner_or_provider"]
        if kind == "location-history":
            data["recorded_by_id"] = self.actor.id
        row = RECORDS[kind](
            organization_id=self.actor.organization_id,
            asset_id=asset_id,
            created_by_id=self.actor.id,
            updated_by_id=self.actor.id,
            **data,
        )
        self.session.add(row)
        await self.session.flush()
        action = {
            "insurance": "insurance_added",
            "registrations": "registration_added",
            "inspections": "inspection_created",
            "defects": "defect_reported",
            "media": "media_added",
            "ownership": "ownership_added",
            "location-history": "location_changed",
        }[kind]
        self.audit("asset." + action, asset_id, row)
        await self.commit()
        return self.public(row)

    async def update_record(self, identifier: uuid.UUID, kind: str, body: Any) -> dict[str, Any]:
        row = await self.ref(RECORDS[kind], identifier, lock=True)
        data = body.model_dump(exclude_unset=True)
        merged = {**{c.key: getattr(row, c.key) for c in inspect(type(row)).columns}, **data}
        await self.validate_fields(merged, row.asset_id)
        if kind == "defects" and row.status in {"RESOLVED", "CANCELLED"}:
            raise ConflictError("Resolved defect history cannot be rewritten")
        if kind == "media" and "is_primary" in data:
            raise ValidationError("Use set-primary to change the primary photo")
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_by_id = self.actor.id
        self.audit(
            "asset." + kind.rstrip("s") + "_updated",
            row.asset_id,
            row,
            {"changes": body.model_dump(mode="json", exclude_unset=True)},
        )
        await self.commit()
        return self.public(row)

    async def resolve_equipment_defect(self, identifier: uuid.UUID, notes: str) -> dict[str, Any]:
        row = await self.ref(AssetDefect, identifier, lock=True)
        if row.status == "RESOLVED":
            raise ConflictError("Defect is already resolved")
        row.status = "RESOLVED"
        row.resolved_at = datetime.now(UTC)
        row.notes = notes
        self.audit("asset.defect_resolved", row.asset_id, row)
        await self.commit()
        return self.public(row)

    async def primary_media(self, identifier: uuid.UUID, archive: bool = False) -> dict[str, Any]:
        row = await self.ref(AssetMedia, identifier)
        asset = await self.asset(row.asset_id, True)
        if archive:
            row.is_active = False
            if row.is_primary:
                row.is_primary = False
                asset.profile_photo_url = None
        else:
            if not row.is_active or row.media_type != "PHOTO":
                raise ValidationError("Choose an active photo")
            await self.session.execute(
                update(AssetMedia)
                .where(
                    AssetMedia.organization_id == self.actor.organization_id,
                    AssetMedia.asset_id == asset.id,
                )
                .values(is_primary=False)
            )
            row.is_primary = True
            asset.profile_photo_url = row.file_url
        self.audit("asset.media_archived" if archive else "asset.media_primary", asset.id, row)
        await self.commit()
        return self.public(row)

    async def add_component(self, asset_id: uuid.UUID, body: Any) -> AssetComponentRead:
        await self.asset(asset_id, True)
        await self.validate_fields(body.model_dump(), asset_id)
        row = AssetComponent(
            organization_id=self.actor.organization_id,
            asset_id=asset_id,
            created_by_id=self.actor.id,
            updated_by_id=self.actor.id,
            **body.model_dump(),
        )
        self.session.add(row)
        await self.session.flush()
        self.audit("asset.component_added", asset_id, row)
        await self.commit()
        return AssetComponentRead.model_validate(row)

    async def change_component(
        self, identifier: uuid.UUID, data: dict[str, Any], replacement: bool = False
    ) -> dict[str, Any]:
        row = await self.ref(AssetComponent, identifier, lock=True)
        await self.validate_fields(data, row.asset_id)
        if replacement:
            if row.status in {
                ComponentStatus.REMOVED,
                ComponentStatus.REPLACED,
                ComponentStatus.SCRAPPED,
            }:
                raise ConflictError("Component is already removed")
            new = AssetComponent(
                organization_id=self.actor.organization_id,
                asset_id=row.asset_id,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
                **data,
            )
            row.status = ComponentStatus.REPLACED
            row.removal_date = date.today()
            row.is_active = False
            self.session.add(new)
            await self.session.flush()
            self.audit(
                "asset.component_replaced", row.asset_id, row, {"replacement_id": str(new.id)}
            )
            await self.commit()
            return self.public(new)
        if row.status in {
            ComponentStatus.REMOVED,
            ComponentStatus.REPLACED,
            ComponentStatus.SCRAPPED,
        }:
            raise ConflictError("Removed component history cannot be rewritten")
        parent = data.get("parent_component_id")
        seen = {row.id}
        while parent:
            if parent in seen:
                raise ValidationError("Component hierarchy cannot contain cycles")
            seen.add(parent)
            parent = (await self.ref(AssetComponent, parent, row.asset_id)).parent_component_id
        if (
            "serial_number" in data
            and row.serial_number
            and data["serial_number"] != row.serial_number
        ):
            raise ValidationError("Use replace to preserve the old component serial number")
        await self.validate_fields(
            {**{c.key: getattr(row, c.key) for c in inspect(AssetComponent).columns}, **data},
            row.asset_id,
        )
        for key, value in data.items():
            setattr(row, key, value)
        self.audit(
            "asset.component_removed"
            if row.status == ComponentStatus.REMOVED
            else "asset.component_updated",
            row.asset_id,
            row,
        )
        await self.commit()
        return self.public(row)

    async def eligibility(self, asset: Asset) -> dict[str, Any]:
        reasons = []
        warnings = []
        if not asset.is_active or asset.archived_at:
            reasons.append("Asset is archived or inactive")
        if asset.status in {
            AssetStatus.DISPOSED,
            AssetStatus.UNDER_MAINTENANCE,
            AssetStatus.BREAKDOWN,
            AssetStatus.OUT_OF_SERVICE,
            AssetStatus.QUARANTINED,
            AssetStatus.LOST,
            AssetStatus.STOLEN,
        }:
            reasons.append("Operational status: " + asset.status.value)
        critical = await self.session.scalar(
            select(AssetDefect.id)
            .where(
                AssetDefect.organization_id == self.actor.organization_id,
                AssetDefect.asset_id == asset.id,
                AssetDefect.status.in_(["OPEN", "ACKNOWLEDGED"]),
                AssetDefect.severity == "CRITICAL",
            )
            .limit(1)
        )
        if critical:
            reasons.append("Open critical defect")
        category = await self.ref(AssetCategory, asset.category_id)
        today = date.today()
        checks: list[tuple[bool, Any, Any, str]] = [
            (category.requires_insurance, AssetInsurance, AssetInsurance.start_date, "Insurance"),
            (
                category.requires_registration,
                AssetRegistration,
                AssetRegistration.issue_date,
                "Registration",
            ),
        ]
        for required, model, start, label in checks:
            if required:
                valid = await self.session.scalar(
                    select(model.id)
                    .where(
                        model.organization_id == self.actor.organization_id,
                        model.asset_id == asset.id,
                        model.status == "ACTIVE",
                        or_(start.is_(None), start <= today),
                        model.expiry_date >= today,
                    )
                    .limit(1)
                )
                if not valid:
                    reasons.append(label + " is missing or expired")
        active = await self.active_assignment(asset.id)
        operator = (active.primary_operator_id if active else None) or asset.primary_operator_id
        if category.requires_operator and not operator:
            warnings.append("Primary operator is not recorded")
        latest = await self.session.scalar(
            select(AssetInspection)
            .where(
                AssetInspection.organization_id == self.actor.organization_id,
                AssetInspection.asset_id == asset.id,
            )
            .order_by(AssetInspection.inspection_date.desc())
            .limit(1)
        )
        if latest and latest.condition_status in {"UNSAFE", "OUT_OF_SERVICE"}:
            reasons.append("Latest inspection marked equipment unsafe")
        eligible = "NOT_ELIGIBLE" if reasons else "WARNING" if warnings else "ELIGIBLE"
        return {
            "operational_eligibility": eligible,
            "reasons": reasons + warnings,
            "is_deployable": not reasons
            and active is None
            and asset.status in {AssetStatus.AVAILABLE, AssetStatus.STANDBY},
            "operational_availability": "UNAVAILABLE"
            if reasons
            else "ASSIGNED"
            if active
            else asset.status.value,
        }

    async def overview(self, asset_id: uuid.UUID) -> dict[str, Any]:
        row = await self.asset(asset_id)
        assignments = await self.list_assignments(asset_id)
        active = await self.active_assignment(asset_id)
        event = await self.session.scalar(
            select(AssetLocationHistory)
            .where(
                AssetLocationHistory.organization_id == self.actor.organization_id,
                AssetLocationHistory.asset_id == asset_id,
            )
            .order_by(
                AssetLocationHistory.recorded_at.desc(), AssetLocationHistory.created_at.desc()
            )
            .limit(1)
        )
        location_id = (
            event.location_id
            if event
            else (active.location_id if active and active.location_id else row.default_location_id)
        )
        location = await self.ref(Location, location_id)
        project = await self.ref(Project, active.project_id) if active else None
        responsible = await self.ref(
            Employee,
            (active.responsible_employee_id if active else None) or row.responsible_employee_id,
        )
        operator = await self.ref(
            Employee, (active.primary_operator_id if active else None) or row.primary_operator_id
        )
        readings = await self.list_meter_readings(asset_id)
        latest = next((r for r in readings if r.reading_type.value == row.meter_type.value), None)
        age = (datetime.now(UTC) - latest.recorded_at).days if latest else None

        def basic(person: Employee | None) -> dict[str, Any] | None:
            if person is None:
                return None
            return {
                key: getattr(person, key)
                for key in ["id", "employee_number", "first_name", "last_name"]
            }

        documents = (
            await self.list_documents(asset_id)
            if self.permitted("assets.documents.read") or self.permitted("asset_documents.read")
            else []
        )
        result = {
            "asset": self.public(row),
            "category": self.public(await self.ref(AssetCategory, row.category_id)),
            "status": row.status,
            "current_assignment": AssetAssignmentRead.model_validate(active) if active else None,
            "current_project": {
                "id": project.id,
                "name": project.name,
                "project_number": project.project_number,
            }
            if project
            else None,
            "current_location": self.public(location) if location else None,
            "responsible_employee": basic(responsible),
            "primary_operator": basic(operator),
            "latest_meter_reading": latest,
            "meter_reading_age_days": age,
            "meter_status": "MISSING"
            if age is None
            else "STALE"
            if age > METER_STALE_DAYS
            else "CURRENT",
            "recent_assignments": assignments[:10],
            "components": await self.list_components(asset_id),
            "documents": documents,
            "expiring_documents": [
                d
                for d in documents
                if d.is_active
                and d.expiry_date
                and d.expiry_date <= date.today() + timedelta(days=30)
            ],
            **await self.eligibility(row),
        }
        for kind, key, permission in [
            ("insurance", "insurance_summary", "assets.insurance.read"),
            ("registrations", "registration_summary", "assets.registration.read"),
            ("inspections", "recent_inspections", "assets.inspections.read"),
            ("defects", "open_defects", "assets.defects.read"),
            ("media", "latest_photos", "assets.media.read"),
        ]:
            result[key] = (
                await self.list_records(asset_id, kind) if self.permitted(permission) else []
            )
        result["open_defects"] = [
            r for r in result["open_defects"] if r["status"] in {"OPEN", "ACKNOWLEDGED"}
        ]
        result["latest_photos"] = [r for r in result["latest_photos"] if r["is_active"]]
        return result

    async def activity(self, asset_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.asset(asset_id)
        rows = (
            await self.session.scalars(
                select(AuditLog)
                .where(
                    AuditLog.organization_id == self.actor.organization_id,
                    or_(
                        AuditLog.entity_id == asset_id,
                        AuditLog.new_values["asset_id"].astext == str(asset_id),
                    ),
                )
                .order_by(AuditLog.created_at.desc())
                .limit(100)
            )
        ).all()
        return [
            {
                "id": str(row.id),
                "action": row.action,
                "occurred_at": row.created_at,
                "entity_id": str(row.entity_id) if row.entity_id else None,
                "entity_type": row.entity_type,
                "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                "old_values": row.old_values,
                "new_values": row.new_values,
            }
            for row in rows
        ]

    async def filtered_assets(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        query = self._scope()
        for key in [
            "category_id",
            "status",
            "ownership_type",
            "responsible_employee_id",
            "primary_operator_id",
            "manufacturer",
            "model",
            "registration_number",
            "serial_number",
            "is_active",
            "meter_type",
        ]:
            if filters.get(key) is not None:
                query = query.where(getattr(Asset, key) == filters[key])
        if filters.get("search"):
            term = "%" + filters["search"] + "%"
            query = query.where(
                or_(
                    *[
                        getattr(Asset, key).ilike(term)
                        for key in [
                            "asset_number",
                            "name",
                            "manufacturer",
                            "model",
                            "serial_number",
                            "registration_number",
                            "engine_number",
                            "vin",
                        ]
                    ]
                )
            )
        rows = (await self.session.scalars(query.order_by(Asset.asset_number))).all()
        results = []
        for row in rows:
            overview = await self.overview(row.id)
            current = overview["current_assignment"]
            if filters.get("project_id") and (
                not current or current.project_id != filters["project_id"]
            ):
                continue
            if filters.get("location_id") and (
                not overview["current_location"]
                or overview["current_location"]["id"] != filters["location_id"]
            ):
                continue
            if filters.get("unassigned_only") and current:
                continue
            if (
                filters.get("is_available") is not None
                and filters["is_available"] != overview["is_deployable"]
            ):
                continue
            if (
                filters.get("operational_eligibility")
                and filters["operational_eligibility"] != overview["operational_eligibility"]
            ):
                continue
            defects = await self.list_records(row.id, "defects")
            opened = [d for d in defects if d["status"] in {"OPEN", "ACKNOWLEDGED"}]
            if (
                filters.get("has_open_defects") is not None
                and bool(opened) != filters["has_open_defects"]
            ):
                continue
            if (
                filters.get("has_critical_defects") is not None
                and any(d["severity"] == "CRITICAL" for d in opened)
                != filters["has_critical_defects"]
            ):
                continue
            match = True
            expiry_models: list[tuple[str, Any]] = [
                ("document_expiring_within_days", AssetDocument),
                ("insurance_expiring_within_days", AssetInsurance),
                ("registration_expiring_within_days", AssetRegistration),
            ]
            for key, model in expiry_models:
                if filters.get(key) is not None:
                    found = await self.session.scalar(
                        select(model.id)
                        .where(
                            model.organization_id == self.actor.organization_id,
                            model.asset_id == row.id,
                            model.expiry_date <= date.today() + timedelta(days=filters[key]),
                        )
                        .limit(1)
                    )
                    match = match and bool(found)
            if match:
                results.append(
                    {
                        **self.public(row),
                        **{
                            k: overview[k]
                            for k in [
                                "current_project",
                                "current_location",
                                "responsible_employee",
                                "primary_operator",
                                "operational_eligibility",
                                "is_deployable",
                                "meter_status",
                                "meter_reading_age_days",
                            ]
                        },
                    }
                )
        return results

    async def fleet_summary(self, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        if project_id:
            await self.ref(Project, project_id)
        rows = await self.filtered_assets({"project_id": project_id})
        counts = Counter(r["status"] for r in rows)
        result = {
            "total_assets": len(rows),
            "total_assets_assigned": sum(bool(r["current_project"]) for r in rows),
            "active_assets": sum(r["is_active"] for r in rows),
            "available_assets": sum(r["is_deployable"] for r in rows),
            "assets_without_recent_meter_reading": sum(
                r["meter_type"] != "NONE" and r["meter_status"] != "CURRENT" for r in rows
            ),
            "assets_without_primary_photo": sum(
                not (r.get("profile_photo_url") or r.get("photo_url")) for r in rows
            ),
            "assets": rows,
        }
        for name, status in [
            ("assigned", "ASSIGNED"),
            ("operating", "OPERATING"),
            ("standby", "STANDBY"),
            ("maintenance", "UNDER_MAINTENANCE"),
            ("breakdown", "BREAKDOWN"),
            ("out_of_service", "OUT_OF_SERVICE"),
        ]:
            result[name + "_assets"] = counts[status]
        for name, key in [("category", "category_id"), ("ownership_type", "ownership_type")]:
            result["assets_by_" + name] = dict(Counter(str(r[key]) for r in rows))
        for name in ["project", "location"]:
            result["assets_by_" + name] = dict(
                Counter(
                    str(r["current_" + name]["name"]) if r["current_" + name] else "Unassigned"
                    for r in rows
                )
            )
        ids = [r["id"] for r in rows]
        summary_models: list[tuple[str, Any]] = [
            ("documents", AssetDocument),
            ("insurance", AssetInsurance),
            ("registrations", AssetRegistration),
        ]
        for name, model in summary_models:
            query = select(model).where(
                model.organization_id == self.actor.organization_id, model.asset_id.in_(ids)
            )
            if hasattr(model, "is_active"):
                query = query.where(model.is_active.is_(True))
            else:
                query = query.where(model.status.notin_(["CANCELLED", "PENDING"]))
            records = (await self.session.scalars(query)).all()
            result["expired_" + name] = sum(
                bool(r.expiry_date and r.expiry_date < date.today()) for r in records
            )
            result["expiring_" + name] = sum(
                bool(
                    r.expiry_date
                    and date.today() <= r.expiry_date <= date.today() + timedelta(days=30)
                )
                for r in records
            )
        result["critical_open_defects"] = await self.session.scalar(
            select(func.count())
            .select_from(AssetDefect)
            .where(
                AssetDefect.organization_id == self.actor.organization_id,
                AssetDefect.asset_id.in_(ids),
                AssetDefect.status.in_(["OPEN", "ACKNOWLEDGED"]),
                AssetDefect.severity == "CRITICAL",
            )
        )
        return result
