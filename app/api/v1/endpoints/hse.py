import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.maintenance_hse import HseIncidentStatus
from app.models.user import User
from app.schemas.maintenance_hse import (
    HseCorrectiveActionCreate,
    HseCorrectiveActionResponse,
    HseCorrectiveActionUpdate,
    HseIncidentCreate,
    HseIncidentResponse,
    HseIncidentUpdate,
)
from app.services import hse as hse_service

router = APIRouter(prefix="/hse", tags=["hse"])


@router.post("/incidents", response_model=HseIncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: HseIncidentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseIncidentResponse:
    incident = await hse_service.create_incident(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return HseIncidentResponse.model_validate(incident)


@router.get("/incidents", response_model=list[HseIncidentResponse])
async def list_incidents(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: uuid.UUID | None = Query(None),
    status: HseIncidentStatus | None = Query(None),
) -> list[HseIncidentResponse]:
    incidents = await hse_service.list_incidents(
        session, current_user.organization_id, project_id=project_id, status=status
    )
    return [HseIncidentResponse.model_validate(inc) for inc in incidents]


@router.get("/incidents/{incident_id}", response_model=HseIncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseIncidentResponse:
    incident = await hse_service.get_incident(
        session, current_user.organization_id, incident_id
    )
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found.")
    return HseIncidentResponse.model_validate(incident)


@router.patch("/incidents/{incident_id}", response_model=HseIncidentResponse)
async def update_incident(
    incident_id: uuid.UUID,
    payload: HseIncidentUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseIncidentResponse:
    try:
        incident = await hse_service.update_incident(
            session, current_user.organization_id, incident_id, payload, actor_id=current_user.id
        )
        return HseIncidentResponse.model_validate(incident)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/incidents/{incident_id}/actions", response_model=HseCorrectiveActionResponse, status_code=status.HTTP_201_CREATED)
async def add_action_to_incident(
    incident_id: uuid.UUID,
    payload: HseCorrectiveActionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseCorrectiveActionResponse:
    try:
        action = await hse_service.add_action_to_incident(
            session, current_user.organization_id, incident_id, payload, actor_id=current_user.id
        )
        return HseCorrectiveActionResponse.model_validate(action)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.patch("/actions/{action_id}", response_model=HseCorrectiveActionResponse)
async def update_action(
    action_id: uuid.UUID,
    payload: HseCorrectiveActionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseCorrectiveActionResponse:
    try:
        action = await hse_service.update_action(
            session, current_user.organization_id, action_id, payload, actor_id=current_user.id
        )
        return HseCorrectiveActionResponse.model_validate(action)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
