import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.employee import AssignmentStatus, Employee, EmployeeAssignment, Position
from app.models.role import Role
from app.models.user import User
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
from app.services.project_sites import require_site, validate_site_intervals


log = logging.getLogger(__name__)


# --- Drilling Program Service ---
async def enrich_program_drilled_metres(
    session: AsyncSession,
    organization_id: uuid.UUID,
    programs: list[DrillingProgram],
) -> None:
    if not programs:
        return

    program_ids = [p.id for p in programs]

    # 1. Sum total_metres from non-archived DrillingShiftReport records directly assigned to program_id
    stmt1 = (
        select(
            DrillingShiftReport.program_id,
            func.coalesce(func.sum(DrillingShiftReport.total_metres), 0),
        )
        .where(
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.archived_at.is_(None),
            DrillingShiftReport.program_id.in_(program_ids),
        )
        .group_by(DrillingShiftReport.program_id)
    )
    res1 = await session.execute(stmt1)
    totals: dict[uuid.UUID, float] = {row[0]: float(row[1]) for row in res1.all()}

    # 2. Sum drilled_metres from DrillingShiftInterval records linked via DrillHole -> program_id
    # for shift reports not already matched by program_id to avoid double counting
    stmt2 = (
        select(
            DrillHole.program_id,
            func.coalesce(func.sum(DrillingShiftInterval.drilled_metres), 0),
        )
        .join(DrillingShiftInterval, DrillingShiftInterval.drill_hole_id == DrillHole.id)
        .join(DrillingShiftReport, DrillingShiftReport.id == DrillingShiftInterval.shift_report_id)
        .where(
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.archived_at.is_(None),
            DrillHole.program_id.in_(program_ids),
            (DrillingShiftReport.program_id.is_(None)) | (DrillingShiftReport.program_id != DrillHole.program_id),
        )
        .group_by(DrillHole.program_id)
    )
    res2 = await session.execute(stmt2)
    for prog_id, metres in res2.all():
        if prog_id:
            totals[prog_id] = totals.get(prog_id, 0.0) + float(metres)

    for prog in programs:
        setattr(prog, "drilled_metres", totals.get(prog.id, 0.0))


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
    await enrich_program_drilled_metres(session, organization_id, [program])
    return program


async def get_drilling_program(
    session: AsyncSession,
    organization_id: uuid.UUID,
    program_id: uuid.UUID,
) -> DrillingProgram | None:
    program = await session.scalar(
        select(DrillingProgram).where(
            DrillingProgram.id == program_id,
            DrillingProgram.organization_id == organization_id,
            DrillingProgram.archived_at.is_(None),
        )
    )
    if program:
        await enrich_program_drilled_metres(session, organization_id, [program])
    return program


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
    programs = list((await session.scalars(stmt)).all())
    await enrich_program_drilled_metres(session, organization_id, programs)
    return programs


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
    await enrich_program_drilled_metres(session, organization_id, [program])
    return program


# --- Drill Hole Service ---
async def create_drill_hole(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: DrillHoleCreate,
    actor_id: uuid.UUID | None = None,
) -> DrillHole:
    await require_site(session, organization_id, payload.project_id, payload.site_location_id)
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
        site_location_id=payload.site_location_id,
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

    if "site_location_id" in payload.model_fields_set:
        await require_site(session, organization_id, hole.project_id, payload.site_location_id)
        if payload.site_location_id != hole.site_location_id and await session.scalar(
            select(DrillingShiftInterval.id).where(DrillingShiftInterval.drill_hole_id == hole.id).limit(1)):
            raise ValueError("A hole with recorded shift intervals cannot be moved to another site")

    for field, val in payload.model_dump(exclude_unset=True, exclude={"from_depth_m", "to_depth_m"}).items():
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


def has_shift_reporting_role(roles):
    keywords = {"supervisor", "manager", "foreman", "lead", "superintendent", "admin", "driller"}
    return any(any(word in (role.name or "").lower() for word in keywords) for role in roles)


# --- Drilling Shift Report Service ---
async def create_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: DrillingShiftReportCreate,
    actor_id: uuid.UUID | None = None,
) -> DrillingShiftReport:
    # Role & Project Assignment Verification for Shift Reporting
    if actor_id is not None:
        user = await session.scalar(select(User).where(User.id == actor_id))
        if user and not user.is_superuser:
            # 1. Supervisor / Management Role Check
            user_roles_query = (
                select(Role)
                .join_from(User, User.roles)
                .where(User.id == actor_id)
                .where(
                    (Role.organization_id == organization_id)
                    | (Role.organization_id.is_(None))
                )
            )
            roles = list((await session.scalars(user_roles_query)).all())

            emp = await session.scalar(
                select(Employee).where(
                    Employee.user_id == actor_id,
                    Employee.organization_id == organization_id,
                    Employee.archived_at.is_(None),
                )
            )

            is_supervisor_role = False
            supervisor_keywords = {"supervisor", "manager", "foreman", "lead", "superintendent", "admin", "driller"}

            is_supervisor_role = has_shift_reporting_role(roles)

            if not is_supervisor_role and emp:
                j_title = (emp.job_title or "").lower()
                if any(kw in j_title for kw in supervisor_keywords):
                    is_supervisor_role = True
                elif emp.position_id:
                    pos = await session.scalar(select(Position).where(Position.id == emp.position_id))
                    if pos and (getattr(pos, "is_supervisory_role", False) or any(kw in (pos.title or "").lower() for kw in supervisor_keywords)):
                        is_supervisor_role = True

            if not is_supervisor_role and emp:
                assignment_as_sup = await session.scalar(
                    select(EmployeeAssignment).where(
                        EmployeeAssignment.organization_id == organization_id,
                        EmployeeAssignment.supervisor_id == emp.id,
                        EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                    )
                )
                if assignment_as_sup:
                    is_supervisor_role = True

            if not is_supervisor_role:
                raise ValueError("Only personnel with a supervisor or management role can create shift production reports.")

            # 2. Project Assignment Check
            if emp:
                proj = await session.scalar(
                    select(Project).where(
                        Project.id == payload.project_id,
                        Project.organization_id == organization_id,
                    )
                )
                is_assigned = bool(proj and proj.project_manager_id == emp.id)

                if not is_assigned:
                    emp_assignment = await session.scalar(
                        select(EmployeeAssignment).where(
                            EmployeeAssignment.organization_id == organization_id,
                            EmployeeAssignment.employee_id == emp.id,
                            EmployeeAssignment.project_id == payload.project_id,
                            EmployeeAssignment.status.in_([AssignmentStatus.ACTIVE, AssignmentStatus.PLANNED]),
                        )
                    )
                    if emp_assignment:
                        is_assigned = True

                if not is_assigned:
                    raise ValueError("You are not assigned to this project. Supervisors can only submit shift reports for projects assigned to them.")
            else:
                raise ValueError("No active employee profile associated with your user account. Cannot verify project assignment.")

    await validate_site_intervals(session, organization_id, payload.project_id,
        payload.site_location_id, payload.intervals)

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

    init_status = payload.status if getattr(payload, "status", None) else ShiftReportStatus.DRAFT

    report = DrillingShiftReport(
        organization_id=organization_id,
        report_number=report_num,
        project_id=payload.project_id,
        site_location_id=payload.site_location_id,
        rig_id=payload.rig_id,
        program_id=payload.program_id,
        date=payload.date,
        shift_type=payload.shift_type,
        supervisor_id=payload.supervisor_id,
        status=init_status,
        submitted_at=datetime.now(UTC) if init_status == ShiftReportStatus.SUBMITTED else None,
        submitted_by_id=actor_id if init_status == ShiftReportStatus.SUBMITTED else None,
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
    report_id = report.id

    # A notification failure must not roll back an already-created shift report.
    if payload.supervisor_id:
        try:
            project = await session.scalar(
                select(Project).where(
                    Project.id == payload.project_id,
                    Project.organization_id == organization_id,
                )
            )
            project_label = project.name if project else str(payload.project_id)

            from app.services.notification_service import notify_assigned_employee

            alert_msg = (
                f"[IMPORTANT] Shift Report Assigned: You have been assigned as supervisor for "
                f"daily shift report '{report_num}' on project '{project_label}' (Date: {payload.date})."
            )
            await notify_assigned_employee(
                session=session,
                organization_id=organization_id,
                employee_id=payload.supervisor_id,
                message=alert_msg,
                domain="DRILLING",
                priority_tag="IMPORTANT",
                actor_id=actor_id,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("notify_assigned_employee failed for shift report %s", report_id)

    return await get_shift_report(session, organization_id, report_id)  # type: ignore[return-value]


async def enrich_shift_reports(session: AsyncSession, reports: list[DrillingShiftReport]) -> None:
    if not reports:
        return
    from app.models.employee import Employee
    from app.models.user import User

    sup_ids = {r.supervisor_id for r in reports if r.supervisor_id}
    sub_ids = {r.submitted_by_id for r in reports if r.submitted_by_id}
    app_ids = {r.approved_by_id for r in reports if r.approved_by_id}
    prj_ids = {r.project_id for r in reports if r.project_id}
    prg_ids = {r.program_id for r in reports if r.program_id}
    rig_ids = {r.rig_id for r in reports if r.rig_id}

    emp_map = {}
    if sup_ids:
        emps = (await session.scalars(select(Employee).where(Employee.id.in_(sup_ids)))).all()
        for e in emps:
            emp_map[e.id] = (
                f"{e.first_name} {e.last_name}".strip(),
                getattr(e, "position_title", None) or getattr(e, "department", None) or "Rig Supervisor"
            )

    user_map = {}
    all_user_ids = sub_ids | app_ids
    if all_user_ids:
        users = (await session.scalars(select(User).where(User.id.in_(all_user_ids)))).all()
        for u in users:
            name = f"{u.first_name} {u.last_name}".strip() or u.email
            user_map[u.id] = (name, getattr(u, "role", "Operations / Field Staff"))

    prj_map = {}
    if prj_ids:
        prjs = (await session.scalars(select(Project).where(Project.id.in_(prj_ids)))).all()
        for p in prjs:
            prj_map[p.id] = p.name

    prg_map = {}
    if prg_ids:
        prgs = (await session.scalars(select(DrillingProgram).where(DrillingProgram.id.in_(prg_ids)))).all()
        for pr in prgs:
            prg_map[pr.id] = pr.name

    rig_map = {}
    if rig_ids:
        rigs = (await session.scalars(select(Asset).where(Asset.id.in_(rig_ids)))).all()
        for rg in rigs:
            rig_map[rg.id] = rg.name

    for r in reports:
        if r.supervisor_id and r.supervisor_id in emp_map:
            name, role = emp_map[r.supervisor_id]
            setattr(r, "supervisor_name", name)
            setattr(r, "supervisor_role", role)
        if r.submitted_by_id and r.submitted_by_id in user_map:
            name, role = user_map[r.submitted_by_id]
            setattr(r, "submitted_by_name", name)
            setattr(r, "submitted_by_role", role)
        if r.approved_by_id and r.approved_by_id in user_map:
            name, role = user_map[r.approved_by_id]
            setattr(r, "approved_by_name", name)
            setattr(r, "approved_by_role", role)
        if r.project_id in prj_map:
            setattr(r, "project_name", prj_map[r.project_id])
        if r.program_id in prg_map:
            setattr(r, "program_name", prg_map[r.program_id])
        if r.rig_id in rig_map:
            setattr(r, "rig_name", rig_map[r.rig_id])


async def get_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
    *, lock: bool = False,
) -> DrillingShiftReport | None:
    query = (
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
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    report = await session.scalar(query)
    if report:
        await enrich_shift_reports(session, [report])
    return report


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
    reports = list((await session.scalars(stmt)).all())
    await enrich_shift_reports(session, reports)
    return reports


async def update_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
    payload: DrillingShiftReportUpdate,
    actor_id: uuid.UUID | None = None,
) -> DrillingShiftReport:
    report = await get_shift_report(session, organization_id, shift_id, lock=True)
    if not report:
        raise ValueError(f"Shift Report {shift_id} not found.")

    if report.status == ShiftReportStatus.APPROVED and not payload.correction_reason:
        raise ValueError("Audited corrections to an APPROVED shift report require a correction_reason.")

    site_id = payload.site_location_id if "site_location_id" in payload.model_fields_set else report.site_location_id
    await validate_site_intervals(session, organization_id, payload.project_id or report.project_id,
        site_id, payload.intervals if payload.intervals is not None else report.intervals, shift_id=report.id)
    report.site_location_id = site_id
    if payload.project_id is not None:
        report.project_id = payload.project_id
    if payload.rig_id is not None:
        report.rig_id = payload.rig_id
    if payload.date is not None:
        report.date = payload.date
    if payload.shift_type is not None:
        report.shift_type = payload.shift_type
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

    if payload.intervals is not None or payload.time_segments is not None:
        recalculate_shift_totals(report)

    if payload.total_metres is not None:
        report.total_metres = payload.total_metres
    if payload.avg_core_recovery_pct is not None:
        report.avg_core_recovery_pct = payload.avg_core_recovery_pct
    if payload.total_productive_hours is not None:
        report.total_productive_hours = payload.total_productive_hours
    if payload.total_nonproductive_hours is not None:
        report.total_nonproductive_hours = payload.total_nonproductive_hours

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
    report = await get_shift_report(session, organization_id, shift_id, lock=True)
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
    # Role & Permission Verification for Shift Report Approval
    user = await session.scalar(select(User).where(User.id == user_id))
    if user and not user.is_superuser:
        user_roles_query = (
            select(Role)
            .options(selectinload(Role.permissions))
            .join_from(User, User.roles)
            .where(User.id == user_id)
            .where(
                (Role.organization_id == organization_id)
                | (Role.organization_id.is_(None))
            )
        )
        roles = list((await session.scalars(user_roles_query)).all())

        user_perm_codes = set()
        for role in roles:
            for perm in role.permissions:
                user_perm_codes.add(perm.code)

        allowed_approval_perms = {"drilling.shifts.approve", "reports.approve", "projects.manage", "projects.update", "drilling.approve"}
        has_approval_perm = bool(user_perm_codes.intersection(allowed_approval_perms))

        approver_keywords = {"manager", "superintendent", "director", "supervisor", "client representative", "admin", "lead", "foreman"}
        has_approver_role = any(
            any(kw in (role.name or "").lower() for kw in approver_keywords)
            for role in roles
        )

        if not (has_approval_perm or has_approver_role):
            raise ValueError(
                "You do not have permission to approve shift reports. Approval requires an authorized management/approval role or permission (drilling.shifts.approve / reports.approve)."
            )

    report = await get_shift_report(session, organization_id, shift_id, lock=True)
    if not report:
        raise ValueError(f"Shift report {shift_id} not found.")

    if report.status not in (ShiftReportStatus.SUBMITTED, ShiftReportStatus.DRAFT, ShiftReportStatus.RETURNED):
        raise ValueError(f"Shift report cannot be approved from status '{report.status}'.")

    if report.status in (ShiftReportStatus.DRAFT, ShiftReportStatus.RETURNED):
        report.submitted_at = report.submitted_at or datetime.now(UTC)
        report.submitted_by_id = report.submitted_by_id or user_id

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
    report = await get_shift_report(session, organization_id, shift_id, lock=True)
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


async def delete_shift_report(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> bool:
    report = await get_shift_report(session, organization_id, shift_id, lock=True)
    if not report:
        raise ValueError(f"Shift report {shift_id} not found.")

    if report.status == ShiftReportStatus.APPROVED:
        raise ValueError("Approved shift production reports cannot be deleted. Only unapproved reports (Draft, Submitted, Returned) can be deleted.")

    await session.delete(report)
    await session.commit()
    return True


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


async def get_shift_daily_context(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_id: uuid.UUID,
) -> dict[str, Any]:
    from app.models.asset import Asset, AssetMeterReading
    from app.models.asset_records import AssetDefect
    from app.services.field_consumables import consumption_rows
    from app.models.maintenance_hse import HseIncident
    from app.models.operational_logs import AssetFuelLog

    report = await get_shift_report(session, organization_id, shift_id)
    if not report:
        raise ValueError(f"Shift Report {shift_id} not found.")

    report_date = report.date
    project_id = report.project_id

    consumptions = [
        {**row, "issue_number": row["document_number"]}
        for row in await consumption_rows(session, organization_id, project_id, report_date)
    ]

    # 2. Fuel Reports & Logs
    fuel_stmt = select(AssetFuelLog).where(
        AssetFuelLog.organization_id == organization_id,
        func.date(AssetFuelLog.recorded_at) == report_date,
        AssetFuelLog.asset_id == report.rig_id,
    )
    fuel_rows = (await session.scalars(fuel_stmt)).all()
    fuel_logs = []
    for f in fuel_rows:
        asset_name = "Asset"
        if f.asset_id:
            ast = await session.scalar(select(Asset).where(Asset.id == f.asset_id))
            if ast:
                asset_name = ast.name
        fuel_logs.append({
            "asset_id": str(f.asset_id),
            "asset_name": asset_name,
            "fuel_quantity": float(f.quantity_litres or 0),
            "fuel_unit": "Litres",
            "total_cost": float(f.quantity_litres * f.unit_cost),
            "meter_reading": float(f.meter_reading) if f.meter_reading is not None else None,
            "operator_name": "",
            "supplier_name": f.supplier or "",
        })

    # 3. Meter Readings
    meter_stmt = select(AssetMeterReading).where(
        AssetMeterReading.organization_id == organization_id,
        func.date(AssetMeterReading.recorded_at) == report_date,
        AssetMeterReading.asset_id == report.rig_id,
    )
    meter_rows = (await session.scalars(meter_stmt)).all()
    meter_readings = []
    for m in meter_rows:
        asset_name = "Asset"
        if m.asset_id:
            ast = await session.scalar(select(Asset).where(Asset.id == m.asset_id))
            if ast:
                asset_name = ast.name
        meter_readings.append({
            "asset_id": str(m.asset_id),
            "asset_name": asset_name,
            "meter_type": str(m.reading_type.value if hasattr(m.reading_type, "value") else m.reading_type),
            "value": float(m.reading or 0),
            "unit": str(m.reading_type.value if hasattr(m.reading_type, "value") else m.reading_type),
            "notes": m.notes or "",
        })

    # 4. Faults & Breakdowns
    defects_stmt = select(AssetDefect).where(
        AssetDefect.organization_id == organization_id,
        func.date(AssetDefect.reported_at) == report_date,
        AssetDefect.asset_id == report.rig_id,
    )
    defects_rows = (await session.scalars(defects_stmt)).all()
    faults = []
    for d in defects_rows:
        asset_name = "Asset"
        if d.asset_id:
            ast = await session.scalar(select(Asset).where(Asset.id == d.asset_id))
            if ast:
                asset_name = ast.name
        faults.append({
            "asset_id": str(d.asset_id),
            "asset_name": asset_name,
            "title": d.title,
            "severity": str(d.severity.value if hasattr(d.severity, "value") else d.severity),
            "status": str(d.status.value if hasattr(d.status, "value") else d.status),
            "description": d.description or "",
        })

    # 5. HSE Incidents
    hse_stmt = select(HseIncident).where(
        HseIncident.organization_id == organization_id,
        HseIncident.project_id == project_id,
        func.date(HseIncident.occurred_at) == report_date,
    )
    hse_rows = (await session.scalars(hse_stmt)).all()
    hse_incidents = []
    for h in hse_rows:
        hse_incidents.append({
            "incident_number": h.incident_number,
            "title": h.title,
            "incident_type": str(h.incident_type.value if hasattr(h.incident_type, "value") else h.incident_type),
            "severity": str(h.severity.value if hasattr(h.severity, "value") else h.severity),
            "status": str(h.status.value if hasattr(h.status, "value") else h.status),
            "description": h.description or "",
        })

    return {
        "shift_id": str(shift_id),
        "report_date": str(report_date),
        "project_id": str(project_id),
        "store_consumptions": consumptions,
        "fuel_reports": fuel_logs,
        "meter_readings": meter_readings,
        "faults_breakdowns": faults,
        "hse_incidents": hse_incidents,
    }
