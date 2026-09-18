import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.client import Client
from app.models.control_tower import (
    ClientProjectGrant,
    ClientPublishedArtifact,
    CommercialOpportunity,
    SupervisorScorecard,
    TenderStage,
)
from app.models.drilling import DrillingShiftReport
from app.models.drilling_commercial import (
    CostSubledgerEntry,
    RevenueSubledgerEntry,
)
from app.models.maintenance_hse import (
    HseIncident,
    MaintenanceWorkOrder,
    WorkOrderStatus,
)
from app.models.organization import Organization
from app.models.project import Project
from app.schemas.control_tower import (
    CeoControlTowerSummaryResponse,
    ClientPortalOverviewResponse,
    ClientProjectGrantCreate,
    CommercialOpportunityCreate,
    CommercialOpportunityUpdate,
    PublishArtifactRequest,
    SupervisorScorecardCreate,
)
from app.services.counters import next_business_number

UTC = timezone.utc


# --- CEO Control Tower Summary ---
async def get_ceo_control_tower_summary(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> CeoControlTowerSummaryResponse:
    org = await session.get(Organization, organization_id)
    org_name = org.name if org else "Cestos Operations"

    # Total projects
    projects_stmt = select(Project).where(
        Project.organization_id == organization_id,
        Project.archived_at.is_(None),
    )
    projects = list((await session.scalars(projects_stmt)).all())

    # Rigs count
    rigs_count = await session.scalar(
        select(func.count(Asset.id)).where(
            Asset.organization_id == organization_id,
            Asset.archived_at.is_(None),
        )
    ) or 0

    # Total Revenue
    rev_stmt = select(func.coalesce(func.sum(RevenueSubledgerEntry.total_revenue_base), 0)).where(
        RevenueSubledgerEntry.organization_id == organization_id,
    )
    total_rev = Decimal(str(await session.scalar(rev_stmt) or 0))

    # Total Cost
    cost_stmt = select(func.coalesce(func.sum(CostSubledgerEntry.total_cost_base), 0)).where(
        CostSubledgerEntry.organization_id == organization_id,
    )
    total_cost = Decimal(str(await session.scalar(cost_stmt) or 0))

    # Total Metres
    metres_stmt = select(func.coalesce(func.sum(DrillingShiftReport.total_metres), 0)).where(
        DrillingShiftReport.organization_id == organization_id,
        DrillingShiftReport.status == "APPROVED",
        DrillingShiftReport.archived_at.is_(None),
    )
    total_metres = Decimal(str(await session.scalar(metres_stmt) or 0))

    # Active WOs & HSE Incidents
    active_wos = await session.scalar(
        select(func.count(MaintenanceWorkOrder.id)).where(
            MaintenanceWorkOrder.organization_id == organization_id,
            MaintenanceWorkOrder.status.in_([WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.WAITING_PARTS]),
            MaintenanceWorkOrder.archived_at.is_(None),
        )
    ) or 0

    open_hse = await session.scalar(
        select(func.count(HseIncident.id)).where(
            HseIncident.organization_id == organization_id,
            HseIncident.status != "CLOSED",
            HseIncident.archived_at.is_(None),
        )
    ) or 0

    net_contribution = total_rev - total_cost
    margin_pct = (net_contribution / total_rev * Decimal("100.0")) if total_rev > 0 else Decimal("0.0")

    # Project-level revenue
    proj_rev_stmt = (
        select(
            RevenueSubledgerEntry.project_id,
            func.coalesce(
                func.sum(RevenueSubledgerEntry.total_revenue_base), 0
            ),
        )
        .where(RevenueSubledgerEntry.organization_id == organization_id)
        .group_by(RevenueSubledgerEntry.project_id)
    )
    proj_rev_rows = (await session.execute(proj_rev_stmt)).all()
    rev_by_proj = {row[0]: Decimal(str(row[1])) for row in proj_rev_rows if row[0]}

    # Project-level cost
    proj_cost_stmt = (
        select(
            CostSubledgerEntry.project_id,
            func.coalesce(
                func.sum(CostSubledgerEntry.total_cost_base), 0
            ),
        )
        .where(CostSubledgerEntry.organization_id == organization_id)
        .group_by(CostSubledgerEntry.project_id)
    )
    proj_cost_rows = (await session.execute(proj_cost_stmt)).all()
    cost_by_proj = {row[0]: Decimal(str(row[1])) for row in proj_cost_rows if row[0]}

    # Project-level metres
    proj_metres_stmt = (
        select(
            DrillingShiftReport.project_id,
            func.coalesce(
                func.sum(DrillingShiftReport.total_metres), 0
            ),
        )
        .where(
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.status == "APPROVED",
            DrillingShiftReport.archived_at.is_(None),
        )
        .group_by(DrillingShiftReport.project_id)
    )
    proj_metres_rows = (await session.execute(proj_metres_stmt)).all()
    metres_by_proj = {row[0]: Decimal(str(row[1])) for row in proj_metres_rows if row[0]}

    project_summaries = []
    for p in projects:
        p_rev = rev_by_proj.get(p.id, Decimal("0.0"))
        p_cost = cost_by_proj.get(p.id, Decimal("0.0"))
        p_metres = metres_by_proj.get(p.id, Decimal("0.0"))
        p_contrib = p_rev - p_cost
        p_margin = (p_contrib / p_rev * Decimal("100.0")) if p_rev > 0 else Decimal("0.0")

        project_summaries.append({
            "project_id": str(p.id),
            "project_name": p.name,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "revenue": float(p_rev),
            "direct_cost": float(p_cost),
            "contribution": float(p_contrib),
            "net_contribution": float(p_contrib),
            "metres_drilled": float(p_metres),
            "contribution_margin_pct": round(float(p_margin), 2),
        })

    return CeoControlTowerSummaryResponse(
        company_name=org_name,
        total_projects=len(projects),
        active_rigs=rigs_count,
        total_revenue=float(total_rev),
        total_direct_cost=float(total_cost),
        net_contribution=float(net_contribution),
        contribution_margin_pct=round(float(margin_pct), 2),
        total_metres_drilled=float(total_metres),
        avg_asset_availability_pct=95.0,  # default baseline
        active_work_orders=active_wos,
        open_hse_incidents=open_hse,
        project_summaries=project_summaries,
    )


# --- Supervisor Scorecard Service ---
async def create_supervisor_scorecard(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: SupervisorScorecardCreate,
    actor_id: uuid.UUID | None = None,
) -> SupervisorScorecard:
    scr_number = await next_business_number(session, organization_id, "supervisor_scorecard")
    
    # Calculate overall weighted score (0 - 100%)
    weighted_tot = (
        payload.production_score +
        payload.rig_condition_score +
        payload.downtime_score +
        payload.hse_score +
        payload.consumables_score +
        payload.crew_management_score +
        payload.reporting_score +
        payload.stewardship_score
    )

    if weighted_tot >= 90:
        grade = "A"
    elif weighted_tot >= 80:
        grade = "B"
    elif weighted_tot >= 70:
        grade = "C"
    elif weighted_tot >= 60:
        grade = "D"
    else:
        grade = "F"

    scorecard = SupervisorScorecard(
        organization_id=organization_id,
        scorecard_number=scr_number,
        supervisor_id=payload.supervisor_id,
        project_id=payload.project_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        production_score=payload.production_score,
        rig_condition_score=payload.rig_condition_score,
        downtime_score=payload.downtime_score,
        hse_score=payload.hse_score,
        consumables_score=payload.consumables_score,
        crew_management_score=payload.crew_management_score,
        reporting_score=payload.reporting_score,
        stewardship_score=payload.stewardship_score,
        overall_weighted_score=weighted_tot,
        grade=grade,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    session.add(scorecard)
    await session.commit()
    await session.refresh(scorecard)
    return scorecard


async def list_supervisor_scorecards(
    session: AsyncSession,
    organization_id: uuid.UUID,
    supervisor_id: uuid.UUID | None = None,
) -> list[SupervisorScorecard]:
    stmt = select(SupervisorScorecard).where(
        SupervisorScorecard.organization_id == organization_id,
        SupervisorScorecard.archived_at.is_(None),
    )
    if supervisor_id:
        stmt = stmt.where(SupervisorScorecard.supervisor_id == supervisor_id)
    stmt = stmt.order_by(SupervisorScorecard.created_at.desc())
    return list((await session.scalars(stmt)).all())


# --- Commercial Opportunities ---
async def create_opportunity(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: CommercialOpportunityCreate,
    actor_id: uuid.UUID | None = None,
) -> CommercialOpportunity:
    opp_number = await next_business_number(session, organization_id, "commercial_opportunity")
    opp = CommercialOpportunity(
        organization_id=organization_id,
        opportunity_number=opp_number,
        client_id=payload.client_id,
        title=payload.title,
        tender_stage=payload.tender_stage,
        win_probability_pct=payload.win_probability_pct,
        estimated_value=payload.estimated_value,
        currency=payload.currency,
        expected_close_date=payload.expected_close_date,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    session.add(opp)
    await session.commit()
    await session.refresh(opp)
    return opp


async def list_opportunities(
    session: AsyncSession,
    organization_id: uuid.UUID,
    client_id: uuid.UUID | None = None,
    tender_stage: TenderStage | None = None,
) -> list[CommercialOpportunity]:
    stmt = select(CommercialOpportunity).where(
        CommercialOpportunity.organization_id == organization_id,
        CommercialOpportunity.archived_at.is_(None),
    )
    if client_id:
        stmt = stmt.where(CommercialOpportunity.client_id == client_id)
    if tender_stage:
        stmt = stmt.where(CommercialOpportunity.tender_stage == tender_stage)
    stmt = stmt.order_by(CommercialOpportunity.created_at.desc())
    return list((await session.scalars(stmt)).all())


async def update_opportunity(
    session: AsyncSession,
    organization_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: CommercialOpportunityUpdate,
    actor_id: uuid.UUID | None = None,
) -> CommercialOpportunity:
    opp = await session.get(CommercialOpportunity, opportunity_id)
    if not opp or opp.organization_id != organization_id:
        raise ValueError(f"Opportunity {opportunity_id} not found.")

    if payload.title is not None:
        opp.title = payload.title
    if payload.tender_stage is not None:
        opp.tender_stage = payload.tender_stage
    if payload.win_probability_pct is not None:
        opp.win_probability_pct = payload.win_probability_pct
    if payload.estimated_value is not None:
        opp.estimated_value = payload.estimated_value
    if payload.expected_close_date is not None:
        opp.expected_close_date = payload.expected_close_date
    if payload.notes is not None:
        opp.notes = payload.notes

    opp.updated_by_id = actor_id
    await session.commit()
    await session.refresh(opp)
    return opp


# --- Client Grants & Portal ---
async def grant_client_project_access(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: ClientProjectGrantCreate,
    actor_id: uuid.UUID | None = None,
) -> ClientProjectGrant:
    grant = ClientProjectGrant(
        organization_id=organization_id,
        client_id=payload.client_id,
        project_id=payload.project_id,
        granted_by_id=actor_id,
        granted_at=datetime.now(UTC),
    )
    session.add(grant)
    await session.commit()
    await session.refresh(grant)
    return grant


async def publish_client_artifact(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: PublishArtifactRequest,
    actor_id: uuid.UUID,
) -> ClientPublishedArtifact:
    pub = ClientPublishedArtifact(
        organization_id=organization_id,
        client_id=payload.client_id,
        project_id=payload.project_id,
        artifact_type=payload.artifact_type,
        entity_id=payload.entity_id,
        title=payload.title,
        description=payload.description,
        published_by_id=actor_id,
        published_at=datetime.now(UTC),
    )
    session.add(pub)
    await session.commit()
    await session.refresh(pub)
    return pub


async def get_client_portal_overview(
    session: AsyncSession,
    organization_id: uuid.UUID,
    client_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ClientPortalOverviewResponse:
    # Verify grant
    grant = await session.scalar(
        select(ClientProjectGrant).where(
            ClientProjectGrant.organization_id == organization_id,
            ClientProjectGrant.client_id == client_id,
            ClientProjectGrant.project_id == project_id,
        )
    )
    if not grant:
        raise ValueError("Client organization has not been granted access to this project.")

    project = await session.get(Project, project_id)
    project_name = project.name if project else "Project"

    stmt = select(ClientPublishedArtifact).where(
        ClientPublishedArtifact.organization_id == organization_id,
        ClientPublishedArtifact.client_id == client_id,
        ClientPublishedArtifact.project_id == project_id,
    ).order_by(ClientPublishedArtifact.published_at.desc())
    artifacts = list((await session.scalars(stmt)).all())

    return ClientPortalOverviewResponse(
        client_id=client_id,
        project_id=project_id,
        project_name=project_name,
        total_published_artifacts=len(artifacts),
        published_artifacts=artifacts,  # type: ignore[arg-type]
    )
