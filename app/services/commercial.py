import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.drilling import DrillingShiftReport
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
from app.models.project import Project
from app.schemas.drilling_commercial import (
    ContractRateCardCreate,
    CostSubledgerEntryCreate,
    ProjectContractCreate,
    ProjectContractUpdate,
    ProjectFinancialSummaryResponse,
    RigPerformanceSummaryResponse,
)

UTC = timezone.utc


# --- Contract & Rate Card Management ---
async def create_project_contract(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: ProjectContractCreate,
    actor_id: uuid.UUID | None = None,
) -> ProjectContract:
    contract = ProjectContract(
        organization_id=organization_id,
        project_id=payload.project_id,
        contract_number=payload.contract_number,
        title=payload.title,
        currency=payload.currency,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    for rc in payload.rate_cards:
        contract.rate_cards.append(
            ContractRateCard(
                organization_id=organization_id,
                rate_type=rc.rate_type,
                drilling_method=rc.drilling_method,
                depth_from_m=rc.depth_from_m,
                depth_to_m=rc.depth_to_m,
                unit_rate=rc.unit_rate,
                description=rc.description,
            )
        )
    session.add(contract)
    await session.commit()
    await session.refresh(contract)
    return contract


async def get_project_contract(
    session: AsyncSession,
    organization_id: uuid.UUID,
    contract_id: uuid.UUID,
) -> ProjectContract | None:
    return await session.scalar(
        select(ProjectContract)
        .options(selectinload(ProjectContract.rate_cards))
        .where(
            ProjectContract.id == contract_id,
            ProjectContract.organization_id == organization_id,
            ProjectContract.archived_at.is_(None),
        )
    )


async def list_project_contracts(
    session: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> list[ProjectContract]:
    stmt = (
        select(ProjectContract)
        .options(selectinload(ProjectContract.rate_cards))
        .where(
            ProjectContract.organization_id == organization_id,
            ProjectContract.archived_at.is_(None),
        )
    )
    if project_id:
        stmt = stmt.where(ProjectContract.project_id == project_id)
    stmt = stmt.order_by(ProjectContract.created_at.desc())
    return list((await session.scalars(stmt)).all())


async def add_rate_card_to_contract(
    session: AsyncSession,
    organization_id: uuid.UUID,
    contract_id: uuid.UUID,
    payload: ContractRateCardCreate,
) -> ContractRateCard:
    contract = await get_project_contract(session, organization_id, contract_id)
    if not contract:
        raise ValueError(f"Project contract {contract_id} not found.")

    card = ContractRateCard(
        organization_id=organization_id,
        contract_id=contract_id,
        rate_type=payload.rate_type,
        drilling_method=payload.drilling_method,
        depth_from_m=payload.depth_from_m,
        depth_to_m=payload.depth_to_m,
        unit_rate=payload.unit_rate,
        description=payload.description,
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return card


# --- Revenue Calculation & Subledger Posting ---
async def calculate_and_post_shift_revenue(
    session: AsyncSession,
    organization_id: uuid.UUID,
    shift_report: DrillingShiftReport,
    actor_id: uuid.UUID | None = None,
) -> list[RevenueSubledgerEntry]:
    """Auto-computes earned revenue for an approved shift report based on active project contract rate cards."""
    # Fetch active contract for the project
    stmt = (
        select(ProjectContract)
        .options(selectinload(ProjectContract.rate_cards))
        .where(
            ProjectContract.organization_id == organization_id,
            ProjectContract.project_id == shift_report.project_id,
            ProjectContract.status == ContractStatus.ACTIVE,
            ProjectContract.archived_at.is_(None),
        )
        .order_by(ProjectContract.start_date.desc())
    )
    contract = (await session.scalars(stmt)).first()
    if not contract:
        # No contract active; no revenue entries posted automatically
        return []

    # Clear existing auto-posted revenue entries for this shift report to prevent duplication upon re-approval
    existing = await session.scalars(
        select(RevenueSubledgerEntry).where(
            RevenueSubledgerEntry.organization_id == organization_id,
            RevenueSubledgerEntry.shift_report_id == shift_report.id,
        )
    )
    for entry in existing.all():
        await session.delete(entry)
    await session.flush()

    posted_entries: list[RevenueSubledgerEntry] = []

    # 1. Metreage Revenue based on Intervals and Depth Bands
    meter_cards = [rc for rc in contract.rate_cards if rc.rate_type == RateType.DRILLING_METER]
    for iv in shift_report.intervals:
        drilled = iv.drilled_metres
        if drilled <= 0:
            continue

        billed_metres_in_iv = Decimal("0.0")
        for rc in meter_cards:
            if rc.drilling_method and iv.drilling_method and rc.drilling_method.lower() != iv.drilling_method.lower():
                continue

            band_from = rc.depth_from_m if rc.depth_from_m is not None else Decimal("0.0")
            band_to = rc.depth_to_m if rc.depth_to_m is not None else Decimal("999999.0")

            overlap_from = max(iv.from_depth_m, band_from)
            overlap_to = min(iv.to_depth_m, band_to)
            overlap_qty = max(Decimal("0.0"), overlap_to - overlap_from)

            if overlap_qty > 0:
                total_rev = overlap_qty * rc.unit_rate
                entry = RevenueSubledgerEntry(
                    organization_id=organization_id,
                    project_id=shift_report.project_id,
                    rig_id=shift_report.rig_id,
                    shift_report_id=shift_report.id,
                    contract_id=contract.id,
                    rate_card_id=rc.id,
                    revenue_category=RevenueCategory.DRILLING_METERAGE,
                    description=f"Drilling meterage {overlap_from}m - {overlap_to}m",
                    quantity=overlap_qty,
                    unit_rate=rc.unit_rate,
                    total_revenue=total_rev,
                    currency=contract.currency,
                    exchange_rate_to_base=Decimal("1.000000"),
                    total_revenue_base=total_rev,
                    posted_at=datetime.now(UTC),
                    created_by_id=actor_id,
                    updated_by_id=actor_id,
                )
                session.add(entry)
                posted_entries.append(entry)
                billed_metres_in_iv += overlap_qty

        # Fallback if no depth band matched
        if billed_metres_in_iv == 0 and meter_cards:
            fallback_card = meter_cards[0]
            total_rev = drilled * fallback_card.unit_rate
            entry = RevenueSubledgerEntry(
                organization_id=organization_id,
                project_id=shift_report.project_id,
                rig_id=shift_report.rig_id,
                shift_report_id=shift_report.id,
                contract_id=contract.id,
                rate_card_id=fallback_card.id,
                revenue_category=RevenueCategory.DRILLING_METERAGE,
                description=f"Drilling meterage {iv.from_depth_m}m - {iv.to_depth_m}m",
                quantity=drilled,
                unit_rate=fallback_card.unit_rate,
                total_revenue=total_rev,
                currency=contract.currency,
                exchange_rate_to_base=Decimal("1.000000"),
                total_revenue_base=total_rev,
                posted_at=datetime.now(UTC),
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
            session.add(entry)
            posted_entries.append(entry)

    # 2. Standby Revenue based on Time Segments
    standby_card = next((rc for rc in contract.rate_cards if rc.rate_type == RateType.STANDBY_HOURLY), None)
    if standby_card:
        standby_hours = sum(ts.hours for ts in shift_report.time_segments if ts.category.value == "STANDBY")
        if standby_hours > 0:
            total_rev = standby_hours * standby_card.unit_rate
            entry = RevenueSubledgerEntry(
                organization_id=organization_id,
                project_id=shift_report.project_id,
                rig_id=shift_report.rig_id,
                shift_report_id=shift_report.id,
                contract_id=contract.id,
                rate_card_id=standby_card.id,
                revenue_category=RevenueCategory.STANDBY_TIME,
                description=f"Rig standby time ({standby_hours} hrs)",
                quantity=standby_hours,
                unit_rate=standby_card.unit_rate,
                total_revenue=total_rev,
                currency=contract.currency,
                exchange_rate_to_base=Decimal("1.000000"),
                total_revenue_base=total_rev,
                posted_at=datetime.now(UTC),
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
            session.add(entry)
            posted_entries.append(entry)

    await session.flush()
    return posted_entries


# --- Cost Posting ---
async def post_cost_entry(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: CostSubledgerEntryCreate,
    actor_id: uuid.UUID | None = None,
) -> CostSubledgerEntry:
    total_cost = payload.quantity * payload.unit_cost
    total_cost_base = total_cost * payload.exchange_rate_to_base

    entry = CostSubledgerEntry(
        organization_id=organization_id,
        project_id=payload.project_id,
        rig_id=payload.rig_id,
        shift_report_id=payload.shift_report_id,
        cost_category=payload.cost_category,
        description=payload.description,
        quantity=payload.quantity,
        unit_of_measure=payload.unit_of_measure,
        unit_cost=payload.unit_cost,
        total_cost=total_cost,
        currency=payload.currency,
        exchange_rate_to_base=payload.exchange_rate_to_base,
        total_cost_base=total_cost_base,
        source_entity_type=payload.source_entity_type,
        source_entity_id=payload.source_entity_id,
        posted_at=datetime.now(UTC),
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


# --- Financial & Performance Summaries ---
async def get_project_financial_summary(
    session: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectFinancialSummaryResponse:
    project = await session.get(Project, project_id)
    if not project or project.organization_id != organization_id:
        raise ValueError(f"Project {project_id} not found.")

    # 1. Total Revenue
    rev_stmt = select(func.coalesce(func.sum(RevenueSubledgerEntry.total_revenue_base), 0)).where(
        RevenueSubledgerEntry.organization_id == organization_id,
        RevenueSubledgerEntry.project_id == project_id,
    )
    total_revenue = Decimal(str(await session.scalar(rev_stmt) or 0))

    # 2. Total Costs by Category
    cost_stmt = (
        select(CostSubledgerEntry.cost_category, func.coalesce(func.sum(CostSubledgerEntry.total_cost_base), 0))
        .where(
            CostSubledgerEntry.organization_id == organization_id,
            CostSubledgerEntry.project_id == project_id,
        )
        .group_by(CostSubledgerEntry.cost_category)
    )
    cost_rows = (await session.execute(cost_stmt)).all()
    cost_breakdown: dict[str, float] = {}
    total_direct_cost = Decimal("0.0")
    for category, amount in cost_rows:
        amt_dec = Decimal(str(amount or 0))
        cat_key = category.value if hasattr(category, "value") else str(category)
        cost_breakdown[cat_key] = float(amt_dec)
        total_direct_cost += amt_dec

    # 3. Metres & Fuel
    metres_stmt = select(func.coalesce(func.sum(DrillingShiftReport.total_metres), 0)).where(
        DrillingShiftReport.organization_id == organization_id,
        DrillingShiftReport.project_id == project_id,
        DrillingShiftReport.status == "APPROVED",
        DrillingShiftReport.archived_at.is_(None),
    )
    total_metres = Decimal(str(await session.scalar(metres_stmt) or 0))

    fuel_cost_stmt = select(func.coalesce(func.sum(CostSubledgerEntry.quantity), 0)).where(
        CostSubledgerEntry.organization_id == organization_id,
        CostSubledgerEntry.project_id == project_id,
        CostSubledgerEntry.cost_category == CostCategory.FUEL,
    )
    total_fuel_litres = Decimal(str(await session.scalar(fuel_cost_stmt) or 0))

    # 4. Net Contribution & Margins
    net_contribution = total_revenue - total_direct_cost
    margin_pct = (net_contribution / total_revenue * Decimal("100.0")) if total_revenue > 0 else Decimal("0.0")
    rev_per_m = (total_revenue / total_metres) if total_metres > 0 else Decimal("0.0")
    cost_per_m = (total_direct_cost / total_metres) if total_metres > 0 else Decimal("0.0")
    litres_per_m = (total_fuel_litres / total_metres) if total_metres > 0 else Decimal("0.0")

    target_var = (total_metres * rev_per_m) - total_direct_cost

    return ProjectFinancialSummaryResponse(
        project_id=project_id,
        currency=project.default_currency or "USD",
        total_revenue=float(total_revenue),
        total_direct_cost=float(total_direct_cost),
        cost_breakdown_by_category=cost_breakdown,
        net_contribution=float(net_contribution),
        contribution_margin_pct=round(float(margin_pct), 2),
        total_metres_drilled=float(total_metres),
        revenue_per_metre=round(float(rev_per_m), 2),
        cost_per_metre=round(float(cost_per_m), 2),
        total_fuel_litres=float(total_fuel_litres),
        litres_per_metre=round(float(litres_per_m), 2),
        target_variance=float(target_var),
    )


async def get_rig_performance_summary(
    session: AsyncSession,
    organization_id: uuid.UUID,
    rig_id: uuid.UUID,
) -> RigPerformanceSummaryResponse:
    rig = await session.get(Asset, rig_id)
    if not rig or rig.organization_id != organization_id:
        raise ValueError(f"Rig asset {rig_id} not found.")

    shifts_stmt = select(
        func.count(DrillingShiftReport.id),
        func.coalesce(func.sum(DrillingShiftReport.total_metres), 0),
        func.coalesce(func.sum(DrillingShiftReport.total_productive_hours), 0),
        func.coalesce(func.sum(DrillingShiftReport.total_nonproductive_hours), 0),
    ).where(
        DrillingShiftReport.organization_id == organization_id,
        DrillingShiftReport.rig_id == rig_id,
        DrillingShiftReport.status == "APPROVED",
        DrillingShiftReport.archived_at.is_(None),
    )
    shift_row = (await session.execute(shifts_stmt)).one()
    shift_count, total_metres, prod_hrs, nonprod_hrs = shift_row
    total_metres = Decimal(str(total_metres or 0))

    rev_stmt = select(func.coalesce(func.sum(RevenueSubledgerEntry.total_revenue_base), 0)).where(
        RevenueSubledgerEntry.organization_id == organization_id,
        RevenueSubledgerEntry.rig_id == rig_id,
    )
    total_revenue = Decimal(str(await session.scalar(rev_stmt) or 0))

    cost_stmt = select(func.coalesce(func.sum(CostSubledgerEntry.total_cost_base), 0)).where(
        CostSubledgerEntry.organization_id == organization_id,
        CostSubledgerEntry.rig_id == rig_id,
    )
    total_cost = Decimal(str(await session.scalar(cost_stmt) or 0))

    net_contribution = total_revenue - total_cost
    margin_pct = (net_contribution / total_revenue * Decimal("100.0")) if total_revenue > 0 else Decimal("0.0")
    cost_per_m = (total_cost / total_metres) if total_metres > 0 else Decimal("0.0")

    return RigPerformanceSummaryResponse(
        rig_id=rig_id,
        rig_name=rig.name,
        currency="USD",
        total_shifts=shift_count or 0,
        total_metres_drilled=float(total_metres),
        total_revenue=float(total_revenue),
        total_direct_cost=float(total_cost),
        net_contribution=float(net_contribution),
        contribution_margin_pct=round(float(margin_pct), 2),
        cost_per_metre=round(float(cost_per_m), 2),
        productive_hours=float(Decimal(str(prod_hrs or 0))),
        nonproductive_hours=float(Decimal(str(nonprod_hrs or 0))),
    )
