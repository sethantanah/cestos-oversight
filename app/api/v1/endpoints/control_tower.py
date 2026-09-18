import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.control_tower import TenderStage
from app.models.user import User
from app.schemas.control_tower import (
    CeoControlTowerSummaryResponse,
    ClientPortalOverviewResponse,
    ClientProjectGrantCreate,
    ClientProjectGrantResponse,
    ClientPublishedArtifactResponse,
    CommercialOpportunityCreate,
    CommercialOpportunityResponse,
    CommercialOpportunityUpdate,
    PublishArtifactRequest,
    SupervisorScorecardCreate,
    SupervisorScorecardResponse,
)
from app.services import control_tower as ct_service

router = APIRouter(prefix="/control-tower", tags=["control-tower"])


@router.get("/summary", response_model=CeoControlTowerSummaryResponse)
async def get_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CeoControlTowerSummaryResponse:
    return await ct_service.get_ceo_control_tower_summary(
        session, current_user.organization_id
    )


@router.post("/scorecards", response_model=SupervisorScorecardResponse, status_code=status.HTTP_201_CREATED)
async def create_scorecard(
    payload: SupervisorScorecardCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupervisorScorecardResponse:
    scorecard = await ct_service.create_supervisor_scorecard(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return SupervisorScorecardResponse.model_validate(scorecard)


@router.get("/scorecards", response_model=list[SupervisorScorecardResponse])
async def list_scorecards(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    supervisor_id: uuid.UUID | None = Query(None),
) -> list[SupervisorScorecardResponse]:
    cards = await ct_service.list_supervisor_scorecards(
        session, current_user.organization_id, supervisor_id=supervisor_id
    )
    return [SupervisorScorecardResponse.model_validate(sc) for sc in cards]


@router.post("/opportunities", response_model=CommercialOpportunityResponse, status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    payload: CommercialOpportunityCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommercialOpportunityResponse:
    opp = await ct_service.create_opportunity(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return CommercialOpportunityResponse.model_validate(opp)


@router.get("/opportunities", response_model=list[CommercialOpportunityResponse])
async def list_opportunities(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    client_id: uuid.UUID | None = Query(None),
    tender_stage: TenderStage | None = Query(None),
) -> list[CommercialOpportunityResponse]:
    opps = await ct_service.list_opportunities(
        session, current_user.organization_id, client_id=client_id, tender_stage=tender_stage
    )
    return [CommercialOpportunityResponse.model_validate(opp) for opp in opps]


@router.patch("/opportunities/{opportunity_id}", response_model=CommercialOpportunityResponse)
async def update_opportunity(
    opportunity_id: uuid.UUID,
    payload: CommercialOpportunityUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommercialOpportunityResponse:
    try:
        opp = await ct_service.update_opportunity(
            session, current_user.organization_id, opportunity_id, payload, actor_id=current_user.id
        )
        return CommercialOpportunityResponse.model_validate(opp)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/client-grants", response_model=ClientProjectGrantResponse, status_code=status.HTTP_201_CREATED)
async def grant_client_project_access(
    payload: ClientProjectGrantCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClientProjectGrantResponse:
    grant = await ct_service.grant_client_project_access(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return ClientProjectGrantResponse.model_validate(grant)


@router.post("/publish", response_model=ClientPublishedArtifactResponse, status_code=status.HTTP_201_CREATED)
async def publish_artifact(
    payload: PublishArtifactRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClientPublishedArtifactResponse:
    artifact = await ct_service.publish_client_artifact(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return ClientPublishedArtifactResponse.model_validate(artifact)


@router.get("/client-portal/{client_id}/{project_id}", response_model=ClientPortalOverviewResponse)
async def get_client_portal_overview(
    client_id: uuid.UUID,
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClientPortalOverviewResponse:
    try:
        return await ct_service.get_client_portal_overview(
            session, current_user.organization_id, client_id, project_id
        )
    except ValueError as err:
        raise HTTPException(status_code=403, detail=str(err))
