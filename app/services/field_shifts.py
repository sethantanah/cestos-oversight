"""Project-scoped, unapproved shift editing from the field portal."""

import uuid
from datetime import date as py_date

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import Asset
from app.models.drilling import DrillHole, ShiftType
from app.schemas.drilling import (
    DrillingShiftIntervalCreate,
    DrillingShiftReportUpdate,
    DrillingShiftTimeSegmentCreate,
)
from app.services import drilling
from app.services.field_equipment import equipment_query, require_project
from app.services.field_work import is_supervisor


class FieldShiftEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_location_id: uuid.UUID | None = None
    date: py_date | None = None
    shift_type: ShiftType | None = None
    rig_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=20000)
    intervals: list[DrillingShiftIntervalCreate] | None = Field(default=None, max_length=200)
    time_segments: list[DrillingShiftTimeSegmentCreate] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_production(self):
        for interval in self.intervals or []:
            drilled = interval.to_depth_m - interval.from_depth_m
            if drilled <= 0:
                raise ValueError("End depth must exceed start depth")
            if interval.core_recovered_m is not None and interval.core_recovered_m > drilled:
                raise ValueError("Recovered core cannot exceed drilled metres")
        if sum(segment.hours for segment in self.time_segments or []) > 24:
            raise ValueError("Shift time cannot exceed 24 hours")
        return self


async def edit_shift(session, actor, shift_id, body):
    if not is_supervisor(actor):
        raise ForbiddenError("Only supervisors can edit field shift reports")
    report = await drilling.get_shift_report(session, actor.organization_id, shift_id, lock=True)
    if report is None:
        raise NotFoundError("Shift report not found")
    await require_project(session, actor, report.project_id)
    if report.status == "APPROVED" or report.approved_at:
        raise ConflictError("Approved shift reports cannot be edited from the field portal")
    if body.rig_id is not None and body.rig_id != report.rig_id:
        if not await session.scalar(
            equipment_query(actor, report.project_id).where(Asset.id == body.rig_id)
        ):
            raise ValidationError("Select equipment currently assigned to this project")
    if body.intervals is not None:
        ids = {interval.drill_hole_id for interval in body.intervals}
        permitted = set(
            (
                await session.scalars(
                    select(DrillHole.id).where(
                        DrillHole.id.in_(ids),
                        DrillHole.organization_id == actor.organization_id,
                        DrillHole.project_id == report.project_id,
                        DrillHole.archived_at.is_(None),
                    )
                )
            ).all()
        )
        if permitted != ids:
            raise ValidationError("Select drill holes from this project")
    payload = DrillingShiftReportUpdate.model_validate(body.model_dump(exclude_unset=True))
    try:
        return await drilling.update_shift_report(
            session,
            actor.organization_id,
            shift_id,
            payload,
            actor_id=actor.id,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
