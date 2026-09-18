import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.drilling import (
    DrillHole,
    DrillHoleStatus,
    DrillingProgram,
    DrillingProgramStatus,
    DrillingShiftCrew,
    DrillingShiftInterval,
    DrillingShiftReport,
    DrillingShiftTimeSegment,
    ShiftReportStatus,
    TimeCategory,
)
from app.models.project import Project
from app.schemas.drilling import (
    DrillHoleCreate,
    DrillHoleUpdate,
    DrillingProgramCreate,
    DrillingProgramUpdate,
    DrillingShiftReportCreate,
    DrillingShiftReportUpdate,
    ProjectDrillingSummaryResponse,
)
from app.services.counters import next_business_number


# --- Drilling Program Service ---
async def create_drilling_program(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: DrillingProgramCreate,
    actor_id: uuid.UUID | None = None,
) -> DrillingProgram:
    project = await session.scalar(
        select(Project).where(
            Project.id == payload.project_id,
            Project.organization_id == organization_id,
        )
    )
    if not project:
        raise ValueError(f"Project {payload.project_id} not found.")

    program = DrillingProgram(
        organization_id=organization_id,
        project_id=payload.project_id,
        name=payload.name,
        code=payload.code,
        target_metres=payload.target_metres,
        start_date=payload.start_date,
        end_date=payload.end_date,
        description=payload.description,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    session.add(program)
    await session.commit()
    await session.refresh(program)
    return program


async def get_drilling_program(
    session: AsyncSession,
    organization_id: uuid.UUID,
    program_id: uuid.UUID,
) -> DrillingProgram | None:
    return await session.scalar(
        select(DrillingProgram).where(
            DrillingProgram.id == program_id,
            DrillingProgram.organization_id == organization_id,
            DrillingProgram.archived_at.is_(None),
        )
    )


async def list_drilling_programs(
    session: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> list[DrillingProgram]:
    stmt = select(DrillingProgram).where(
        DrillingProgram.organization_id == organization_id,
        DrillingProgram.archived_at.is_(None),
    )
    if project_id:
        stmt = stmt.where(DrillingProgram.project_id == project_id)
    stmt = stmt.order_by(DrillingProgram.created_at.desc())
    return list((await session.scalars(stmt)).all())


async def update_drilling_program(
    session: AsyncSession,
    organization_id: uuid.UUID,
    program_id: uuid.UUID,
    payload: DrillingProgramUpdate,
) -> DrillingProgram:
    program = await get_drilling_program(session, organization_id, program_id)
    if not program:
        raise ValueError(f"Drilling Program {program_id} not found.")

    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(program, field, val)

    await session.commit()
    await session.refresh(program)
    return program


# --- Drill Hole Service ---
async def create_drill_hole(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: DrillHoleCreate,
    actor_id: uuid.UUID | None = None,
) -> DrillHole:
    # Check duplicate hole number within project
    existing = await session.scalar(
        select(DrillHole).where(
            DrillHole.organization_id == organization_id,
            DrillHole.project_id == payload.project_id,
            DrillHole.hole_number == payload.hole_number,
            DrillHole.archived_at.is_(None),
        )
    )
    if existing:
        raise ValueError(f"Drill hole '{payload.hole_number}' already exists in this project.")

    hole = DrillHole(
        organization_id=organization_id,
        project_id=payload.project_id,
        program_id=payload.program_id,
        hole_number=payload.hole_number,
        drilling_method=payload.drilling_method,
        target_depth_m=payload.target_depth_m,
        azimuth_deg=payload.azimuth_deg,
        dip_deg=payload.dip_deg,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    session.add(hole)
    await session.commit()
    await session.refresh(hole)
    return hole


async def get_drill_hole(
    session: AsyncSession,
    organization_id: uuid.UUID,
    hole_id: uuid.UUID,
) -> DrillHole | None:
    return await session.scalar(
        select(DrillHole).where(
            DrillHole.id == hole_id,
            DrillHole.organization_id == organization_id,
            DrillHole.archived_at.is_(None),
        )
    )


async def list_drill_holes(
    session: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
) -> list[DrillHole]:
    stmt = select(DrillHole).where(
        DrillHole.organization_id == organization_id,
        DrillHole.archived_at.is_(None),
    )
    if project_id:
        stmt = stmt.where(DrillHole.project_id == project_id)
    if program_id:
        stmt = stmt.where(DrillHole.program_id == program_id)
    stmt = stmt.order_by(DrillHole.hole_number)
    return list((await session.scalars(stmt)).all())


async def update_drill_hole(
    session: AsyncSession,
    organization_id: uuid.UUID,
    hole_id: uuid.UUID,
    payload: DrillHoleUpdate,
) -> DrillHole:
    hole = await get_drill_hole(session, organization_id, hole_id)
    if not hole:
        raise ValueError(f"Drill Hole {hole_id} not found.")

    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(hole, field, val)

    await session.commit()
    await session.refresh(hole)
    return hole


# --- Helper Metrics Calculation ---
def recalculate_shift_totals(report: DrillingShiftReport) -> None:
    tot_m = Decimal("0.0")
    total_recovered = Decimal("0.0")
    total_drilled_with_recovery = Decimal("0.0")

    for interval in report.intervals:
        drilled = interval.to_depth_m - interval.from_depth_m
        if drilled < 0:
            raise ValueError(f"Interval to_depth_m ({interval.to_depth_m}) cannot be less than from_depth_m ({interval.from_depth_m}).")
        interval.drilled_metres = drilled
        if interval.core_recovered_m is not None and drilled > 0:
            pct = (interval.core_recovered_m / drilled) * Decimal("100.0")
            interval.core_recovery_pct = round(pct, 2)
            total_recovered += interval.core_recovered_m
            total_drilled_with_recovery += drilled
        else:
            interval.core_recovery_pct = None
        tot_m += drilled

    prod_hours = Decimal("0.0")
    nonprod_hours = Decimal("0.0")

    for segment in report.time_segments:
        if segment.category == TimeCategory.PRODUCTIVE:
            prod_hours += segment.hours
        else:
            nonprod_hours += segment.hours

    report.total_metres = tot_m
    report.total_productive_hours = prod_hours
    report.total_nonproductive_hours = nonprod_hours
    if total_drilled_with_recovery > 0:
        report.avg_core_recovery_pct = round((total_recovered / total_drilled_with_recovery) * Decimal("100.0"), 2)
    else:
        report.avg_core_recovery_pct = None


# --- Drilling Shift Report Service ---
async def create_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: DrillingShiftReportCreate,
    actor_id: uuid.UUID | None = None,
) -> DrillingShiftReport:
    # Check Rig existence
    rig = await session.scalar(
        select(Asset).where(Asset.id == payload.rig_id, Asset.organization_id == organization_id)
    )
    if not rig:
        raise ValueError(f"Rig asset {payload.rig_id} not found.")

    # Idempotency / machine time conflict check
    existing = await session.scalar(
        select(DrillingShiftReport).where(
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.rig_id == payload.rig_id,
            DrillingShiftReport.date == payload.date,
            DrillingShiftReport.shift_type == payload.shift_type,
            DrillingShiftReport.archived_at.is_(None),
        )
    )
    if existing:
        raise ValueError(f"A shift report for rig '{rig.name}', date {payload.date}, and {payload.shift_type} shift already exists.")

    report_num = await next_business_number(session, organization_id, "drilling_shift")

    report = DrillingShiftReport(
        organization_id=organization_id,
        report_number=report_num,
        project_id=payload.project_id,
        rig_id=payload.rig_id,
        program_id=payload.program_id,
        date=payload.date,
        shift_type=payload.shift_type,
        supervisor_id=payload.supervisor_id,
        status=ShiftReportStatus.DRAFT,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )

    for iv in payload.intervals:
        drilled = iv.to_depth_m - iv.from_depth_m
        if drilled < 0:
            raise ValueError("to_depth_m cannot be less than from_depth_m.")
        rec_pct = (iv.core_recovered_m / drilled * Decimal("100.0")) if (iv.core_recovered_m is not None and drilled > 0) else None
        report.intervals.append(
            DrillingShiftInterval(
                organization_id=organization_id,
                drill_hole_id=iv.drill_hole_id,
                from_depth_m=iv.from_depth_m,
                to_depth_m=iv.to_depth_m,
                drilled_metres=drilled,
                core_recovered_m=iv.core_recovered_m,
                core_recovery_pct=round(rec_pct, 2) if rec_pct is not None else None,
                drilling_method=iv.drilling_method,
                ground_conditions=iv.ground_conditions,
            )
        )

    for ts in payload.time_segments:
        report.time_segments.append(
            DrillingShiftTimeSegment(
                organization_id=organization_id,
                category=ts.category,
                reason_code=ts.reason_code,
                hours=ts.hours,
                comments=ts.comments,
            )
        )

    for cm in payload.crew_members:
        report.crew_members.append(
            DrillingShiftCrew(
                organization_id=organization_id,
                employee_id=cm.employee_id,
                role_on_shift=cm.role_on_shift,
                hours_worked=cm.hours_worked,
            )
        )

    recalculate_shift_totals(report)

    session.add(report)
    await session.commit()
    return await get_shift_report(session, organization_id, report.id)  # type: ignore[return-value]


async def get_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
) -> DrillingShiftReport | None:
    return await session.scalar(
        select(DrillingShiftReport)
        .options(
            selectinload(DrillingShiftReport.intervals),
            selectinload(DrillingShiftReport.time_segments),
            selectinload(DrillingShiftReport.crew_members),
        )
        .where(
            DrillingShiftReport.id == shift_id,
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.archived_at.is_(None),
        )
    )


async def list_shift_reports(
    session: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    rig_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: ShiftReportStatus | None = None,
) -> list[DrillingShiftReport]:
    stmt = (
        select(DrillingShiftReport)
        .options(
            selectinload(DrillingShiftReport.intervals),
            selectinload(DrillingShiftReport.time_segments),
            selectinload(DrillingShiftReport.crew_members),
        )
        .where(
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.archived_at.is_(None),
        )
    )
    if project_id:
        stmt = stmt.where(DrillingShiftReport.project_id == project_id)
    if rig_id:
        stmt = stmt.where(DrillingShiftReport.rig_id == rig_id)
    if date_from:
        stmt = stmt.where(DrillingShiftReport.date >= date_from)
    if date_to:
        stmt = stmt.where(DrillingShiftReport.date <= date_to)
    if status:
        stmt = stmt.where(DrillingShiftReport.status == status)

    stmt = stmt.order_by(DrillingShiftReport.date.desc(), DrillingShiftReport.created_at.desc())
    return list((await session.scalars(stmt)).all())


async def update_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
    payload: DrillingShiftReportUpdate,
    actor_id: uuid.UUID | None = None,
) -> DrillingShiftReport:
    report = await get_shift_report(session, organization_id, shift_id)
    if not report:
        raise ValueError(f"Shift Report {shift_id} not found.")

    if report.status == ShiftReportStatus.APPROVED and not payload.correction_reason:
        raise ValueError("Audited corrections to an APPROVED shift report require a correction_reason.")

    if payload.program_id is not None:
        report.program_id = payload.program_id
    if payload.supervisor_id is not None:
        report.supervisor_id = payload.supervisor_id
    if payload.notes is not None:
        report.notes = payload.notes
    if payload.correction_reason is not None:
        report.correction_reason = payload.correction_reason

    # Replace intervals if provided
    if payload.intervals is not None:
        report.intervals.clear()
        for iv in payload.intervals:
            drilled = iv.to_depth_m - iv.from_depth_m
            rec_pct = (iv.core_recovered_m / drilled * Decimal("100.0")) if (iv.core_recovered_m is not None and drilled > 0) else None
            report.intervals.append(
                DrillingShiftInterval(
                    organization_id=organization_id,
                    drill_hole_id=iv.drill_hole_id,
                    from_depth_m=iv.from_depth_m,
                    to_depth_m=iv.to_depth_m,
                    drilled_metres=drilled,
                    core_recovered_m=iv.core_recovered_m,
                    core_recovery_pct=round(rec_pct, 2) if rec_pct is not None else None,
                    drilling_method=iv.drilling_method,
                    ground_conditions=iv.ground_conditions,
                )
            )

    # Replace time segments if provided
    if payload.time_segments is not None:
        report.time_segments.clear()
        for ts in payload.time_segments:
            report.time_segments.append(
                DrillingShiftTimeSegment(
                    organization_id=organization_id,
                    category=ts.category,
                    reason_code=ts.reason_code,
                    hours=ts.hours,
                    comments=ts.comments,
                )
            )

    # Replace crew members if provided
    if payload.crew_members is not None:
        report.crew_members.clear()
        for cm in payload.crew_members:
            report.crew_members.append(
                DrillingShiftCrew(
                    organization_id=organization_id,
                    employee_id=cm.employee_id,
                    role_on_shift=cm.role_on_shift,
                    hours_worked=cm.hours_worked,
                )
            )

    recalculate_shift_totals(report)
    report.updated_by_id = actor_id
    await session.commit()
    return await get_shift_report(session, organization_id, report.id)  # type: ignore[return-value]


# --- State Machine Workflows ---
async def submit_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
    user_id: uuid.UUID,
    notes: str | None = None,
) -> DrillingShiftReport:
    report = await get_shift_report(session, organization_id, shift_id)
    if not report:
        raise ValueError(f"Shift report {shift_id} not found.")

    if report.status not in (ShiftReportStatus.DRAFT, ShiftReportStatus.RETURNED):
        raise ValueError(f"Shift report cannot be submitted from status '{report.status}'.")

    report.status = ShiftReportStatus.SUBMITTED
    report.submitted_at = datetime.now(UTC)
    report.submitted_by_id = user_id
    if notes:
        report.notes = (report.notes or "") + f"\nSubmit notes: {notes}"

    await session.commit()
    res = await get_shift_report(session, organization_id, report.id)
    assert res is not None
    return res


async def approve_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
    user_id: uuid.UUID,
    notes: str | None = None,
) -> DrillingShiftReport:
    report = await get_shift_report(session, organization_id, shift_id)
    if not report:
        raise ValueError(f"Shift report {shift_id} not found.")

    if report.status != ShiftReportStatus.SUBMITTED:
        raise ValueError(f"Shift report cannot be approved from status '{report.status}'. Only SUBMITTED reports can be approved.")

    report.status = ShiftReportStatus.APPROVED
    report.approved_at = datetime.now(UTC)
    report.approved_by_id = user_id
    if notes:
        report.notes = (report.notes or "") + f"\nApproval notes: {notes}"

    # Update final depth and status of drill holes involved in this shift
    for interval in report.intervals:
        hole = await session.get(DrillHole, interval.drill_hole_id)
        if hole and hole.organization_id == organization_id:
            if hole.final_depth_m is None or interval.to_depth_m > hole.final_depth_m:
                hole.final_depth_m = interval.to_depth_m
            if hole.status == DrillHoleStatus.PLANNED:
                hole.status = DrillHoleStatus.IN_PROGRESS
                hole.started_at = hole.started_at or datetime.now(UTC)

    from app.services.commercial import calculate_and_post_shift_revenue
    await calculate_and_post_shift_revenue(session, organization_id, report, actor_id=user_id)

    await session.commit()
    res = await get_shift_report(session, organization_id, report.id)
    assert res is not None
    return res


async def return_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
) -> DrillingShiftReport:
    report = await get_shift_report(session, organization_id, shift_id)
    if not report:
        raise ValueError(f"Shift report {shift_id} not found.")

    if report.status != ShiftReportStatus.SUBMITTED:
        raise ValueError(f"Shift report cannot be returned from status '{report.status}'.")

    report.status = ShiftReportStatus.RETURNED
    report.return_reason = reason

    await session.commit()
    res = await get_shift_report(session, organization_id, report.id)
    assert res is not None
    return res


# --- Project Drilling Summary ---
async def get_project_drilling_summary(
    session: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectDrillingSummaryResponse:
    # 1. Programs count
    prog_count = await session.scalar(
        select(func.count(DrillingProgram.id)).where(
            DrillingProgram.organization_id == organization_id,
            DrillingProgram.project_id == project_id,
            DrillingProgram.archived_at.is_(None),
        )
    ) or 0

    # 2. Holes breakdown
    total_holes = await session.scalar(
        select(func.count(DrillHole.id)).where(
            DrillHole.organization_id == organization_id,
            DrillHole.project_id == project_id,
            DrillHole.archived_at.is_(None),
        )
    ) or 0

    active_holes = await session.scalar(
        select(func.count(DrillHole.id)).where(
            DrillHole.organization_id == organization_id,
            DrillHole.project_id == project_id,
            DrillHole.status == DrillHoleStatus.IN_PROGRESS,
            DrillHole.archived_at.is_(None),
        )
    ) or 0

    completed_holes = await session.scalar(
        select(func.count(DrillHole.id)).where(
            DrillHole.organization_id == organization_id,
            DrillHole.project_id == project_id,
            DrillHole.status == DrillHoleStatus.COMPLETED,
            DrillHole.archived_at.is_(None),
        )
    ) or 0

    # 3. Shifts
    submitted_shifts = await session.scalar(
        select(func.count(DrillingShiftReport.id)).where(
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.project_id == project_id,
            DrillingShiftReport.status == ShiftReportStatus.SUBMITTED,
            DrillingShiftReport.archived_at.is_(None),
        )
    ) or 0

    approved_shifts = await session.scalar(
        select(func.count(DrillingShiftReport.id)).where(
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.project_id == project_id,
            DrillingShiftReport.status == ShiftReportStatus.APPROVED,
            DrillingShiftReport.archived_at.is_(None),
        )
    ) or 0

    # 4. Aggregated metres & hours from APPROVED shifts
    approved_reports = (
        await session.scalars(
            select(DrillingShiftReport).where(
                DrillingShiftReport.organization_id == organization_id,
                DrillingShiftReport.project_id == project_id,
                DrillingShiftReport.status == ShiftReportStatus.APPROVED,
                DrillingShiftReport.archived_at.is_(None),
            )
        )
    ).all()

    tot_metres = Decimal("0.0")
    tot_prod_hrs = Decimal("0.0")
    tot_standby_hrs = Decimal("0.0")
    tot_maint_hrs = Decimal("0.0")
    tot_core_rec_m = Decimal("0.0")
    tot_drilled_rec_m = Decimal("0.0")

    for rep in approved_reports:
        tot_metres += rep.total_metres
        tot_prod_hrs += rep.total_productive_hours
        for ts in rep.time_segments:
            if ts.category == TimeCategory.STANDBY:
                tot_standby_hrs += ts.hours
            elif ts.category == TimeCategory.MAINTENANCE:
                tot_maint_hrs += ts.hours

        for iv in rep.intervals:
            if iv.core_recovered_m is not None:
                tot_core_rec_m += iv.core_recovered_m
                tot_drilled_rec_m += iv.drilled_metres

    avg_recovery = round((tot_core_rec_m / tot_drilled_rec_m * Decimal("100.0")), 2) if tot_drilled_rec_m > 0 else None

    return ProjectDrillingSummaryResponse(
        project_id=project_id,
        total_programs=prog_count,
        total_holes=total_holes,
        active_holes=active_holes,
        completed_holes=completed_holes,
        total_shifts_submitted=submitted_shifts,
        total_shifts_approved=approved_shifts,
        total_metres_drilled=tot_metres,
        total_productive_hours=tot_prod_hrs,
        total_standby_hours=tot_standby_hrs,
        total_maintenance_hours=tot_maint_hrs,
        overall_avg_core_recovery_pct=avg_recovery,
    )
