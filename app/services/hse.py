import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.maintenance_hse import (
    HseActionStatus,
    HseCorrectiveAction,
    HseIncident,
    HseIncidentStatus,
)
from app.schemas.maintenance_hse import (
    HseCorrectiveActionCreate,
    HseCorrectiveActionUpdate,
    HseIncidentCreate,
    HseIncidentUpdate,
)
from app.services.counters import next_business_number
from app.services.project_sites import require_site

UTC = timezone.utc


async def create_incident(
    session: AsyncSession,
    organization_id: uuid.UUID,
    payload: HseIncidentCreate,
    actor_id: uuid.UUID | None = None,
) -> HseIncident:
    if payload.site_location_id:
        if not payload.project_id:
            raise ValueError("A project is required when selecting a site")
        await require_site(session, organization_id, payload.project_id, payload.site_location_id)
    inc_number = await next_business_number(session, organization_id, "hse_incident")
    incident = HseIncident(
        organization_id=organization_id,
        incident_number=inc_number,
        title=payload.title,
        incident_type=payload.incident_type,
        severity=payload.severity,
        status=HseIncidentStatus.REPORTED,
        occurred_at=payload.occurred_at,
        project_id=payload.project_id,
        site_location_id=payload.site_location_id,
        asset_id=payload.asset_id,
        reported_by_id=payload.reported_by_id,
        description=payload.description,
        immediate_actions_taken=payload.immediate_actions_taken,
        root_cause_analysis=payload.root_cause_analysis,
        notes=payload.notes,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    for act in payload.actions:
        act_number = await next_business_number(session, organization_id, "hse_corrective_action")
        incident.actions.append(
            HseCorrectiveAction(
                organization_id=organization_id,
                action_number=act_number,
                description=act.description,
                assigned_to_id=act.assigned_to_id,
                due_date=act.due_date,
                status=HseActionStatus.OPEN,
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
        )
    session.add(incident)
    await session.commit()
    return await get_incident(session, organization_id, incident.id)  # type: ignore[return-value]


async def get_incident(
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> HseIncident | None:
    return await session.scalar(
        select(HseIncident)
        .options(selectinload(HseIncident.actions))
        .where(
            HseIncident.id == incident_id,
            HseIncident.organization_id == organization_id,
            HseIncident.archived_at.is_(None),
        )
    )


async def list_incidents(
    session: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    status: HseIncidentStatus | None = None,
) -> list[HseIncident]:
    stmt = (
        select(HseIncident)
        .options(selectinload(HseIncident.actions))
        .where(
            HseIncident.organization_id == organization_id,
            HseIncident.archived_at.is_(None),
        )
    )
    if project_id:
        stmt = stmt.where(HseIncident.project_id == project_id)
    if status:
        stmt = stmt.where(HseIncident.status == status)

    stmt = stmt.order_by(HseIncident.occurred_at.desc())
    return list((await session.scalars(stmt)).all())


async def update_incident(
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    payload: HseIncidentUpdate,
    actor_id: uuid.UUID | None = None,
) -> HseIncident:
    incident = await get_incident(session, organization_id, incident_id)
    if not incident:
        raise ValueError(f"HSE incident {incident_id} not found.")

    if payload.title is not None:
        incident.title = payload.title
    if payload.incident_type is not None:
        incident.incident_type = payload.incident_type
    if payload.severity is not None:
        incident.severity = payload.severity
    if payload.status is not None:
        incident.status = payload.status
    if payload.description is not None:
        incident.description = payload.description
    if payload.immediate_actions_taken is not None:
        incident.immediate_actions_taken = payload.immediate_actions_taken
    if payload.root_cause_analysis is not None:
        incident.root_cause_analysis = payload.root_cause_analysis
    if payload.notes is not None:
        incident.notes = payload.notes

    incident.updated_by_id = actor_id
    await session.commit()
    return await get_incident(session, organization_id, incident.id)  # type: ignore[return-value]


async def add_action_to_incident(
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    payload: HseCorrectiveActionCreate,
    actor_id: uuid.UUID | None = None,
) -> HseCorrectiveAction:
    incident = await get_incident(session, organization_id, incident_id)
    if not incident:
        raise ValueError(f"HSE incident {incident_id} not found.")

    act_number = await next_business_number(session, organization_id, "hse_corrective_action")
    action = HseCorrectiveAction(
        organization_id=organization_id,
        action_number=act_number,
        incident_id=incident_id,
        description=payload.description,
        assigned_to_id=payload.assigned_to_id,
        due_date=payload.due_date,
        status=HseActionStatus.OPEN,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return action


async def update_action(
    session: AsyncSession,
    organization_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: HseCorrectiveActionUpdate,
    actor_id: uuid.UUID | None = None,
) -> HseCorrectiveAction:
    action = await session.get(HseCorrectiveAction, action_id)
    if not action or action.organization_id != organization_id:
        raise ValueError(f"HSE action {action_id} not found.")

    if payload.description is not None:
        action.description = payload.description
    if payload.assigned_to_id is not None:
        action.assigned_to_id = payload.assigned_to_id
    if payload.due_date is not None:
        action.due_date = payload.due_date
    if payload.status is not None:
        action.status = payload.status
        if payload.status == HseActionStatus.CLOSED and not action.closed_at:
            action.closed_at = datetime.now(UTC)
            action.closed_by_id = actor_id
    if payload.closure_notes is not None:
        action.closure_notes = payload.closure_notes

    await session.commit()
    await session.refresh(action)
    return action
