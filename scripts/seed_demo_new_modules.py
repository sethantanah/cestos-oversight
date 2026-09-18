"""Development seed script for new module additions (Phases 1 - 6).

Usage: uv run python -m scripts.seed_demo_new_modules
Idempotent: skips records that already exist.
Requires base seed (organization, roles, permissions) to exist.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.models import Asset, Client, Employee, Project, User
from app.models.operational_logs import FuelSupplier
from app.models.control_tower import (
    ClientArtifactType,
    ClientProjectGrant,
    ClientPublishedArtifact,
    CommercialOpportunity,
    SupervisorScorecard,
    TenderStage,
)
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
    ShiftType,
    TimeCategory,
)
from app.models.drilling_commercial import (
    ContractRateCard,
    ContractStatus,
    CostCategory,
    CostSubledgerEntry,
    ProjectContract,
    RateType,
    RevenueCategory,
    RevenueSubledgerEntry,
)
from app.models.maintenance_hse import (
    FailureTaxonomy,
    HseActionStatus,
    HseCorrectiveAction,
    HseIncident,
    HseIncidentStatus,
    HseIncidentType,
    HseSeverity,
    MaintenanceWorkOrder,
    WorkOrderCostLine,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)
from app.models.procurement import PoStatus, PurchaseOrder, PurchaseOrderItem
from app.services.counters import next_business_number
from scripts.seed import ORGANIZATION_ID


async def seed_new_modules(session: AsyncSession) -> None:
    # Serialize concurrent execution
    await session.execute(text("SELECT pg_advisory_xact_lock(736284903)"))

    async def number(entity: str) -> str:
        return await next_business_number(session, ORGANIZATION_ID, entity)

    # 1. Fetch prerequisite entities
    client = (
        await session.scalars(
            select(Client).where(Client.organization_id == ORGANIZATION_ID)
        )
    ).first()
    if not client:
        client = Client(
            organization_id=ORGANIZATION_ID,
            client_number=await number("client"),
            name="Demo Mining Client A",
            country="LR",
        )
        session.add(client)
        await session.flush()

    project = (
        await session.scalars(
            select(Project).where(Project.organization_id == ORGANIZATION_ID)
        )
    ).first()
    if not project:
        project = Project(
            organization_id=ORGANIZATION_ID,
            project_number=await number("project"),
            name="Project Alpha",
            client_id=client.id,
            status="ACTIVE",
        )
        session.add(project)
        await session.flush()

    rig = (
        await session.scalars(
            select(Asset).where(Asset.organization_id == ORGANIZATION_ID)
        )
    ).first()
    if not rig:
        rig = Asset(
            organization_id=ORGANIZATION_ID,
            asset_number=await number("asset"),
            name="CDR-001 Rig",
            category_id=None,
            status="ACTIVE",
        )
        session.add(rig)
        await session.flush()

    employee = (
        await session.scalars(
            select(Employee).where(Employee.organization_id == ORGANIZATION_ID)
        )
    ).first()

    # 2. Drilling Programs & Holes
    prog = (
        await session.scalars(
            select(DrillingProgram).where(
                DrillingProgram.organization_id == ORGANIZATION_ID,
                DrillingProgram.project_id == project.id,
            )
        )
    ).first()
    if not prog:
        prog = DrillingProgram(
            organization_id=ORGANIZATION_ID,
            project_id=project.id,
            name="Nimba Exploration RC Drilling Program 2026",
            code="PROG-RC-2026",
            target_metres=Decimal("5000.00"),
            status=DrillingProgramStatus.ACTIVE,
            start_date=date(2026, 1, 15),
            end_date=date(2026, 6, 30),
            description="Reverse Circulation infill drilling campaign across Nimba targets.",
        )
        session.add(prog)
        await session.flush()

    hole1 = (
        await session.scalars(
            select(DrillHole).where(
                DrillHole.organization_id == ORGANIZATION_ID,
                DrillHole.hole_number == "HOLE-RC-001",
            )
        )
    ).first()
    if not hole1:
        hole1 = DrillHole(
            organization_id=ORGANIZATION_ID,
            project_id=project.id,
            program_id=prog.id,
            hole_number="HOLE-RC-001",
            drilling_method="RC",
            target_depth_m=Decimal("250.00"),
            final_depth_m=Decimal("248.50"),
            azimuth_deg=Decimal("180.00"),
            dip_deg=Decimal("-60.00"),
            status=DrillHoleStatus.COMPLETED,
        )
        session.add(hole1)
        await session.flush()

    # 3. Drilling Shift Production Reports
    shift1 = (
        await session.scalars(
            select(DrillingShiftReport).where(
                DrillingShiftReport.organization_id == ORGANIZATION_ID,
                DrillingShiftReport.report_number == "DS-2026-001",
            )
        )
    ).first()
    if not shift1:
        shift1 = DrillingShiftReport(
            organization_id=ORGANIZATION_ID,
            project_id=project.id,
            rig_id=rig.id,
            program_id=prog.id,
            report_number="DS-2026-001",
            date=date(2026, 2, 10),
            shift_type=ShiftType.DAY,
            total_metres=Decimal("120.50"),
            avg_core_recovery_pct=Decimal("96.50"),
            total_productive_hours=Decimal("10.00"),
            total_nonproductive_hours=Decimal("2.00"),
            status=ShiftReportStatus.APPROVED,
            supervisor_id=employee.id if employee else None,
        )
        session.add(shift1)
        await session.flush()

        # Add sample interval & time segment
        session.add(
            DrillingShiftInterval(
                organization_id=ORGANIZATION_ID,
                shift_report_id=shift1.id,
                drill_hole_id=hole1.id,
                from_depth_m=Decimal("0.00"),
                to_depth_m=Decimal("50.00"),
                drilled_metres=Decimal("50.00"),
                core_recovery_pct=Decimal("98.00"),
            )
        )
        session.add(
            DrillingShiftTimeSegment(
                organization_id=ORGANIZATION_ID,
                shift_report_id=shift1.id,
                category=TimeCategory.PRODUCTIVE,
                reason_code="RC_DRILLING",
                hours=Decimal("8.00"),
                comments="Active RC drilling from 0 to 80m",
            )
        )
        if employee:
            session.add(
                DrillingShiftCrew(
                    organization_id=ORGANIZATION_ID,
                    shift_report_id=shift1.id,
                    employee_id=employee.id,
                    role_on_shift="DRILLER",
                    hours_worked=Decimal("12.00"),
                )
            )

    shift2 = (
        await session.scalars(
            select(DrillingShiftReport).where(
                DrillingShiftReport.organization_id == ORGANIZATION_ID,
                DrillingShiftReport.report_number == "DS-2026-002",
            )
        )
    ).first()
    if not shift2:
        shift2 = DrillingShiftReport(
            organization_id=ORGANIZATION_ID,
            project_id=project.id,
            rig_id=rig.id,
            program_id=prog.id,
            report_number="DS-2026-002",
            date=date(2026, 2, 11),
            shift_type=ShiftType.NIGHT,
            total_metres=Decimal("98.00"),
            avg_core_recovery_pct=Decimal("94.20"),
            total_productive_hours=Decimal("9.00"),
            total_nonproductive_hours=Decimal("3.00"),
            status=ShiftReportStatus.SUBMITTED,
            supervisor_id=employee.id if employee else None,
        )
        session.add(shift2)
        await session.flush()

    # 4. Commercial Contracts & Rate Cards
    contract = (
        await session.scalars(
            select(ProjectContract).where(
                ProjectContract.organization_id == ORGANIZATION_ID,
                ProjectContract.contract_number == "CON-2026-001",
            )
        )
    ).first()
    if not contract:
        contract = ProjectContract(
            organization_id=ORGANIZATION_ID,
            project_id=project.id,
            contract_number="CON-2026-001",
            title="Master RC Drilling Rate Agreement",
            currency="USD",
            start_date=date(2026, 1, 1),
            status=ContractStatus.ACTIVE,
        )
        session.add(contract)
        await session.flush()

        session.add_all(
            [
                ContractRateCard(
                    organization_id=ORGANIZATION_ID,
                    contract_id=contract.id,
                    rate_type=RateType.DRILLING_METER,
                    drilling_method="RC",
                    depth_from_m=Decimal("0.00"),
                    depth_to_m=Decimal("100.00"),
                    unit_rate=Decimal("65.00"),
                    description="RC meterage rate 0-100m",
                ),
                ContractRateCard(
                    organization_id=ORGANIZATION_ID,
                    contract_id=contract.id,
                    rate_type=RateType.DRILLING_METER,
                    drilling_method="RC",
                    depth_from_m=Decimal("100.00"),
                    depth_to_m=Decimal("250.00"),
                    unit_rate=Decimal("75.00"),
                    description="RC meterage rate 100-250m",
                ),
                ContractRateCard(
                    organization_id=ORGANIZATION_ID,
                    contract_id=contract.id,
                    rate_type=RateType.STANDBY_HOURLY,
                    unit_rate=Decimal("150.00"),
                    description="Client-caused standby rate",
                ),
            ]
        )
        await session.flush()

    # 5. Financial Subledger Entries & Shifts across all Project Sites
    all_projects = list(
        (
            await session.scalars(
                select(Project).where(
                    Project.organization_id == ORGANIZATION_ID,
                    Project.archived_at.is_(None),
                )
            )
        ).all()
    )

    sample_metrics = [
        {"rev": Decimal("18450.00"), "cost": Decimal("11200.00"), "metres": Decimal("284.00")},
        {"rev": Decimal("24600.00"), "cost": Decimal("14800.00"), "metres": Decimal("378.00")},
        {"rev": Decimal("15200.00"), "cost": Decimal("8900.00"), "metres": Decimal("230.00")},
        {"rev": Decimal("12800.00"), "cost": Decimal("7600.00"), "metres": Decimal("195.00")},
        {"rev": Decimal("21300.00"), "cost": Decimal("12500.00"), "metres": Decimal("325.00")},
        {"rev": Decimal("16700.00"), "cost": Decimal("9800.00"), "metres": Decimal("256.00")},
        {"rev": Decimal("19500.00"), "cost": Decimal("11900.00"), "metres": Decimal("300.00")},
        {"rev": Decimal("14200.00"), "cost": Decimal("8400.00"), "metres": Decimal("218.00")},
        {"rev": Decimal("11500.00"), "cost": Decimal("6900.00"), "metres": Decimal("177.00")},
    ]

    for idx, p in enumerate(all_projects):
        metrics = sample_metrics[idx % len(sample_metrics)]

        # Ensure approved shift report exists for metres
        has_proj_shift = (
            await session.scalars(
                select(DrillingShiftReport).where(
                    DrillingShiftReport.organization_id == ORGANIZATION_ID,
                    DrillingShiftReport.project_id == p.id,
                )
            )
        ).first()
        if not has_proj_shift:
            session.add(
                DrillingShiftReport(
                    organization_id=ORGANIZATION_ID,
                    project_id=p.id,
                    rig_id=rig.id,
                    program_id=prog.id,
                    report_number=f"DS-2026-P{idx+1:03d}",
                    date=date(2026, 2, 10 + (idx % 15)),
                    shift_type=ShiftType.DAY,
                    total_metres=metrics["metres"],
                    avg_core_recovery_pct=Decimal("95.50"),
                    total_productive_hours=Decimal("10.00"),
                    total_nonproductive_hours=Decimal("2.00"),
                    status=ShiftReportStatus.APPROVED,
                    supervisor_id=employee.id if employee else None,
                )
            )

        # Revenue
        has_p_rev = (
            await session.scalars(
                select(RevenueSubledgerEntry).where(
                    RevenueSubledgerEntry.organization_id == ORGANIZATION_ID,
                    RevenueSubledgerEntry.project_id == p.id,
                )
            )
        ).first()
        if not has_p_rev:
            session.add(
                RevenueSubledgerEntry(
                    organization_id=ORGANIZATION_ID,
                    project_id=p.id,
                    rig_id=rig.id,
                    contract_id=contract.id,
                    revenue_category=RevenueCategory.DRILLING_METERAGE,
                    description=f"{metrics['metres']}m RC Drilling Revenue ({p.name})",
                    quantity=metrics["metres"],
                    unit_rate=metrics["rev"] / metrics["metres"],
                    total_revenue=metrics["rev"],
                    total_revenue_base=metrics["rev"],
                    currency="USD",
                    posted_at=datetime(2026, 2, 10, 18, 0, tzinfo=UTC),
                )
            )

        # Cost
        has_p_cost = (
            await session.scalars(
                select(CostSubledgerEntry).where(
                    CostSubledgerEntry.organization_id == ORGANIZATION_ID,
                    CostSubledgerEntry.project_id == p.id,
                )
            )
        ).first()
        if not has_p_cost:
            session.add(
                CostSubledgerEntry(
                    organization_id=ORGANIZATION_ID,
                    project_id=p.id,
                    rig_id=rig.id,
                    cost_category=CostCategory.FUEL,
                    description=f"Direct Site Operational & Consumable Costs ({p.name})",
                    quantity=Decimal("1.00"),
                    unit_of_measure="LOT",
                    unit_cost=metrics["cost"],
                    total_cost=metrics["cost"],
                    total_cost_base=metrics["cost"],
                    currency="USD",
                    posted_at=datetime(2026, 2, 10, 18, 0, tzinfo=UTC),
                )
            )
    await session.flush()

    # 6. Maintenance Work Orders
    wo = (
        await session.scalars(
            select(MaintenanceWorkOrder).where(
                MaintenanceWorkOrder.organization_id == ORGANIZATION_ID,
                MaintenanceWorkOrder.wo_number == "WO-2026-001",
            )
        )
    ).first()
    if not wo:
        wo = MaintenanceWorkOrder(
            organization_id=ORGANIZATION_ID,
            wo_number="WO-2026-001",
            asset_id=rig.id,
            project_id=project.id,
            title="500-Hour Scheduled Rig Maintenance & Filter Service",
            description="Complete oil filter, air filter, and hydraulic oil replacement.",
            work_type=WorkOrderType.PREVENTIVE,
            priority=WorkOrderPriority.HIGH,
            status=WorkOrderStatus.COMPLETED,
            failure_taxonomy=FailureTaxonomy.HYDRAULIC,
            downtime_hours=Decimal("2.50"),
            assigned_technician_id=employee.id if employee else None,
            completed_at=datetime(2026, 2, 8, 16, 0, tzinfo=UTC),
        )
        session.add(wo)
        await session.flush()

        session.add_all(
            [
                WorkOrderCostLine(
                    organization_id=ORGANIZATION_ID,
                    work_order_id=wo.id,
                    cost_type="PARTS",
                    description="High Pressure Hydraulic Hose 20ft",
                    quantity=Decimal("2.00"),
                    unit_cost=Decimal("180.00"),
                    total_cost=Decimal("360.00"),
                ),
                WorkOrderCostLine(
                    organization_id=ORGANIZATION_ID,
                    work_order_id=wo.id,
                    cost_type="LABOUR",
                    description="Senior Mechanic 7 Hours Servicing",
                    quantity=Decimal("7.00"),
                    unit_cost=Decimal("70.00"),
                    total_cost=Decimal("490.00"),
                ),
            ]
        )

    # 7. HSE Incidents & CAPA Actions
    inc = (
        await session.scalars(
            select(HseIncident).where(
                HseIncident.organization_id == ORGANIZATION_ID,
                HseIncident.incident_number == "INC-2026-001",
            )
        )
    ).first()
    if not inc and employee:
        inc = HseIncident(
            organization_id=ORGANIZATION_ID,
            incident_number="INC-2026-001",
            project_id=project.id,
            asset_id=rig.id,
            incident_type=HseIncidentType.NEAR_MISS,
            severity=HseSeverity.LOW,
            status=HseIncidentStatus.CLOSED,
            title="Minor Hydraulic Fitting Weep at Rig Feed Cylinder",
            description="During pre-shift inspection, driller noticed slow oil weep from quick release coupler.",
            occurred_at=datetime(2026, 2, 5, 7, 30, tzinfo=UTC),
            reported_by_id=employee.id,
        )
        session.add(inc)
        await session.flush()

        session.add(
            HseCorrectiveAction(
                organization_id=ORGANIZATION_ID,
                incident_id=inc.id,
                action_number="CAPA-2026-001",
                description="Replace quick disconnect coupling and re-torque fittings on hydraulic manifold joints.",
                assigned_to_id=employee.id,
                due_date=date(2026, 2, 10),
                status=HseActionStatus.CLOSED,
                closed_at=datetime(2026, 2, 5, 9, 0, tzinfo=UTC),
            )
        )

    # 8. Fuel Supplier & Procurement Purchase Orders
    supplier = (
        await session.scalars(
            select(FuelSupplier).where(FuelSupplier.organization_id == ORGANIZATION_ID)
        )
    ).first()
    if not supplier:
        supplier = FuelSupplier(
            organization_id=ORGANIZATION_ID,
            name="TotalEnergies Liberia Ltd",
        )
        session.add(supplier)
        await session.flush()

    po1 = (
        await session.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == ORGANIZATION_ID,
                PurchaseOrder.po_number == "PO-2026-001",
            )
        )
    ).first()
    if not po1:
        po1 = PurchaseOrder(
            organization_id=ORGANIZATION_ID,
            po_number="PO-2026-001",
            supplier_id=supplier.id,
            project_id=project.id,
            status=PoStatus.RECEIVED,
            total_amount=Decimal("4500.00"),
            currency="USD",
            notes="Consumables order for RC drill bits.",
        )
        session.add(po1)
        await session.flush()

        session.add(
            PurchaseOrderItem(
                organization_id=ORGANIZATION_ID,
                purchase_order_id=po1.id,
                description="7-1/4 Diamond Matrix RC Drill Bits",
                quantity_ordered=Decimal("10.00"),
                quantity_received=Decimal("10.00"),
                unit_price=Decimal("450.00"),
                total_price=Decimal("4500.00"),
            )
        )

    po2 = (
        await session.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == ORGANIZATION_ID,
                PurchaseOrder.po_number == "PO-2026-002",
            )
        )
    ).first()
    if not po2:
        po2 = PurchaseOrder(
            organization_id=ORGANIZATION_ID,
            po_number="PO-2026-002",
            supplier_id=supplier.id,
            project_id=project.id,
            status=PoStatus.PARTIALLY_RECEIVED,
            total_amount=Decimal("1800.00"),
            currency="USD",
            notes="Low Sulfur Diesel Bulk Fuel Order.",
        )
        session.add(po2)
        await session.flush()

        session.add(
            PurchaseOrderItem(
                organization_id=ORGANIZATION_ID,
                purchase_order_id=po2.id,
                description="Low Sulfur Diesel (2,000 Litres)",
                quantity_ordered=Decimal("2000.00"),
                quantity_received=Decimal("1000.00"),
                unit_price=Decimal("0.90"),
                total_price=Decimal("1800.00"),
            )
        )

    # 9. CEO Control Tower: Scorecards, Tenders, Client Portal Grants & Artifacts
    if employee:
        sc = (
            await session.scalars(
                select(SupervisorScorecard).where(
                    SupervisorScorecard.organization_id == ORGANIZATION_ID,
                    SupervisorScorecard.scorecard_number == "SC-2026-001",
                )
            )
        ).first()
        if not sc:
            session.add(
                SupervisorScorecard(
                    organization_id=ORGANIZATION_ID,
                    scorecard_number="SC-2026-001",
                    supervisor_id=employee.id,
                    project_id=project.id,
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 1, 31),
                    production_score=Decimal("23.00"),
                    rig_condition_score=Decimal("18.50"),
                    downtime_score=Decimal("14.00"),
                    hse_score=Decimal("14.50"),
                    consumables_score=Decimal("9.00"),
                    crew_management_score=Decimal("4.50"),
                    reporting_score=Decimal("4.50"),
                    stewardship_score=Decimal("4.50"),
                    overall_weighted_score=Decimal("92.50"),
                    grade="A",
                    notes="Outstanding performance on target meterage and Zero LTI.",
                )
            )

    opp1 = (
        await session.scalars(
            select(CommercialOpportunity).where(
                CommercialOpportunity.organization_id == ORGANIZATION_ID,
                CommercialOpportunity.opportunity_number == "OPP-2026-001",
            )
        )
    ).first()
    if not opp1:
        session.add(
            CommercialOpportunity(
                organization_id=ORGANIZATION_ID,
                opportunity_number="OPP-2026-001",
                client_id=client.id,
                title="Grand Bassa Infill Diamond Drilling Tender 2026",
                tender_stage=TenderStage.PROPOSAL_SENT,
                win_probability_pct=Decimal("75.00"),
                estimated_value=Decimal("450000.00"),
                currency="USD",
                expected_close_date=date(2026, 4, 15),
                notes="Formal proposal submitted following site visit.",
            )
        )

    opp2 = (
        await session.scalars(
            select(CommercialOpportunity).where(
                CommercialOpportunity.organization_id == ORGANIZATION_ID,
                CommercialOpportunity.opportunity_number == "OPP-2026-002",
            )
        )
    ).first()
    if not opp2:
        session.add(
            CommercialOpportunity(
                organization_id=ORGANIZATION_ID,
                opportunity_number="OPP-2026-002",
                client_id=client.id,
                title="Bong County RC Extension Campaign",
                tender_stage=TenderStage.QUALIFIED,
                win_probability_pct=Decimal("60.00"),
                estimated_value=Decimal("280000.00"),
                currency="USD",
                expected_close_date=date(2026, 5, 30),
                notes="EOI approved; preparing tender dossier.",
            )
        )

    user = (await session.scalars(select(User))).first()
    if user:
        grant = (
            await session.scalars(
                select(ClientProjectGrant).where(
                    ClientProjectGrant.organization_id == ORGANIZATION_ID,
                    ClientProjectGrant.client_id == client.id,
                    ClientProjectGrant.project_id == project.id,
                )
            )
        ).first()
        if not grant:
            session.add(
                ClientProjectGrant(
                    organization_id=ORGANIZATION_ID,
                    client_id=client.id,
                    project_id=project.id,
                    granted_by_id=user.id,
                    granted_at=datetime.now(UTC),
                )
            )

        art = (
            await session.scalars(
                select(ClientPublishedArtifact).where(
                    ClientPublishedArtifact.organization_id == ORGANIZATION_ID,
                    ClientPublishedArtifact.title == "Q1 2026 Drilling Production Summary & HSE Report",
                )
            )
        ).first()
        if not art:
            session.add(
                ClientPublishedArtifact(
                    organization_id=ORGANIZATION_ID,
                    client_id=client.id,
                    project_id=project.id,
                    entity_id=prog.id,
                    title="Q1 2026 Drilling Production Summary & HSE Report",
                    description="Executive Q1 drilling progress, core recovery percentages, and HSE incident log.",
                    artifact_type=ClientArtifactType.PROGRESS_SUMMARY,
                    published_by_id=user.id,
                    published_at=datetime.now(UTC),
                )
            )

    print("New module seed complete.")


async def main() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                await seed_new_modules(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=loop_factory)
