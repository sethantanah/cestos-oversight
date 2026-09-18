import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.procurement import PoStatus
from app.models.user import User
from app.schemas.procurement import (
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    ReceiveGoodsRequest,
)
from app.services import procurement as procurement_service

router = APIRouter(prefix="/procurement", tags=["procurement"])


@router.post("/purchase-orders", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    po = await procurement_service.create_purchase_order(
        session, current_user.organization_id, payload, actor_id=current_user.id
    )
    return PurchaseOrderResponse.model_validate(po)


@router.get("/purchase-orders", response_model=list[PurchaseOrderResponse])
async def list_purchase_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    supplier_id: uuid.UUID | None = Query(None),
    status: PoStatus | None = Query(None),
) -> list[PurchaseOrderResponse]:
    orders = await procurement_service.list_purchase_orders(
        session, current_user.organization_id, supplier_id=supplier_id, status=status
    )
    return [PurchaseOrderResponse.model_validate(po) for po in orders]


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    po_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    po = await procurement_service.get_purchase_order(
        session, current_user.organization_id, po_id
    )
    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase order {po_id} not found.")
    return PurchaseOrderResponse.model_validate(po)


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderResponse)
async def receive_goods(
    po_id: uuid.UUID,
    payload: ReceiveGoodsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    try:
        po = await procurement_service.receive_goods(
            session, current_user.organization_id, po_id, payload
        )
        return PurchaseOrderResponse.model_validate(po)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
