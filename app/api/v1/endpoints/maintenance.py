import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.maintenance_hse import WorkOrderStatus
from app.models.user import User
from app.schemas.maintenance_hse import (
    AssetReliabilitySummaryResponse,
    CompleteWorkOrderRequest,
    MaintenanceWorkOrderCreate,
    MaintenanceWorkOrderResponse,
    MaintenanceWorkOrderUpdate,
    WorkOrderCostLineCreate,
    WorkOrderCostLineResponse,
)
from app.services import maintenance as maintenance_service

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.post("/work-orders", response_model=MaintenanceWorkOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_work_order(
    payload: MaintenanceWorkOrderCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWorkOrderResponse:
    wo = await maintenance_service.create_work_order(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return MaintenanceWorkOrderResponse.model_validate(wo)


@router.get("/work-orders", response_model=list[MaintenanceWorkOrderResponse])
async def list_work_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    asset_id: uuid.UUID | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    status: WorkOrderStatus | None = Query(None),
) -> list[MaintenanceWorkOrderResponse]:
    work_orders = await maintenance_service.list_work_orders(
        session, current_user.organization_id, asset_id=asset_id, project_id=project_id, status=status
    )
    return [MaintenanceWorkOrderResponse.model_validate(wo) for wo in work_orders]


@router.get("/work-orders/{wo_id}", response_model=MaintenanceWorkOrderResponse)
async def get_work_order(
    wo_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWorkOrderResponse:
    wo = await maintenance_service.get_work_order(
        session, current_user.organization_id, wo_id
    )
    if not wo:
        raise HTTPException(status_code=404, detail=f"Work order {wo_id} not found.")
    return MaintenanceWorkOrderResponse.model_validate(wo)


@router.patch("/work-orders/{wo_id}", response_model=MaintenanceWorkOrderResponse)
async def update_work_order(
    wo_id: uuid.UUID,
    payload: MaintenanceWorkOrderUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWorkOrderResponse:
    wo = await maintenance_service.get_work_order(session, current_user.organization_id, wo_id)
    if not wo:
        raise HTTPException(status_code=404, detail=f"Work order {wo_id} not found.")
    if wo.created_at < datetime.now(timezone.utc) - timedelta(days=10):
        raise HTTPException(status_code=409, detail="Work orders can only be edited within 10 days of creation.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(wo, key, value)
    wo.updated_by_id = current_user.id
    wo.updated_at = datetime.now(timezone.utc)
    await session.commit()
    wo = await maintenance_service.get_work_order(session, current_user.organization_id, wo_id)
    return MaintenanceWorkOrderResponse.model_validate(wo)


@router.post("/work-orders/{wo_id}/cost-lines", response_model=WorkOrderCostLineResponse, status_code=status.HTTP_201_CREATED)
async def add_cost_line(
    wo_id: uuid.UUID,
    payload: WorkOrderCostLineCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkOrderCostLineResponse:
    try:
        line = await maintenance_service.add_cost_line_to_work_order(
            session, current_user.organization_id, wo_id, payload
        )
        return WorkOrderCostLineResponse.model_validate(line)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/work-orders/{wo_id}/complete", response_model=MaintenanceWorkOrderResponse)
async def complete_work_order(
    wo_id: uuid.UUID,
    payload: CompleteWorkOrderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWorkOrderResponse:
    try:
        wo = await maintenance_service.complete_work_order(
            session, current_user.organization_id, wo_id, user_id=current_user.id, payload=payload
        )
        return MaintenanceWorkOrderResponse.model_validate(wo)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.get("/assets/{asset_id}/reliability", response_model=AssetReliabilitySummaryResponse)
async def get_asset_reliability(
    asset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetReliabilitySummaryResponse:
    try:
        return await maintenance_service.get_asset_reliability_summary(
            session, current_user.organization_id, asset_id
        )
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))
