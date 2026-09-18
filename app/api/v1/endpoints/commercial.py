import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.drilling_commercial import (
    ContractRateCardCreate,
    ContractRateCardResponse,
    CostSubledgerEntryCreate,
    CostSubledgerEntryResponse,
    ProjectContractCreate,
    ProjectContractResponse,
    ProjectContractUpdate,
    ProjectFinancialSummaryResponse,
    RigPerformanceSummaryResponse,
)
from app.services import commercial as commercial_service

router = APIRouter(prefix="/commercial", tags=["commercial"])


@router.post("/contracts", response_model=ProjectContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    payload: ProjectContractCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectContractResponse:
    contract = await commercial_service.create_project_contract(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return ProjectContractResponse.model_validate(contract)


@router.get("/contracts", response_model=list[ProjectContractResponse])
async def list_contracts(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: uuid.UUID | None = Query(None),
) -> list[ProjectContractResponse]:
    contracts = await commercial_service.list_project_contracts(
        session, current_user.organization_id, project_id=project_id
    )
    return [ProjectContractResponse.model_validate(c) for c in contracts]


@router.get("/contracts/{contract_id}", response_model=ProjectContractResponse)
async def get_contract(
    contract_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectContractResponse:
    contract = await commercial_service.get_project_contract(
        session, current_user.organization_id, contract_id
    )
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
    return ProjectContractResponse.model_validate(contract)


@router.patch("/contracts/{contract_id}", response_model=ProjectContractResponse)
async def update_contract(
    contract_id: uuid.UUID,
    payload: ProjectContractUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectContractResponse:
    contract = await commercial_service.update_project_contract(
        session, current_user.organization_id, contract_id, payload, actor_id=current_user.id
    )
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
    return ProjectContractResponse.model_validate(contract)


@router.post("/contracts/{contract_id}/rate-cards", response_model=ContractRateCardResponse, status_code=status.HTTP_201_CREATED)
async def add_rate_card(
    contract_id: uuid.UUID,
    payload: ContractRateCardCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContractRateCardResponse:
    try:
        card = await commercial_service.add_rate_card_to_contract(
            session, current_user.organization_id, contract_id, payload
        )
        return ContractRateCardResponse.model_validate(card)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/cost-entries", response_model=CostSubledgerEntryResponse, status_code=status.HTTP_201_CREATED)
async def post_cost(
    payload: CostSubledgerEntryCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CostSubledgerEntryResponse:
    entry = await commercial_service.post_cost_entry(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return CostSubledgerEntryResponse.model_validate(entry)


@router.get("/projects/{project_id}/financials", response_model=ProjectFinancialSummaryResponse)
async def get_project_financials(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectFinancialSummaryResponse:
    try:
        return await commercial_service.get_project_financial_summary(
            session, current_user.organization_id, project_id
        )
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))


@router.get("/rigs/{rig_id}/performance", response_model=RigPerformanceSummaryResponse)
async def get_rig_performance(
    rig_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RigPerformanceSummaryResponse:
    try:
        return await commercial_service.get_rig_performance_summary(
            session, current_user.organization_id, rig_id
        )
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))
