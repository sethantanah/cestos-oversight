import uuid
from urllib.parse import urlencode
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, request_storage
from app.db.session import get_session
from app.models.procurement import PoStatus
from app.models.operational_logs import OperationalExpense, OperationalExpensePayment
from app.models.user import User
from app.models.role import Role, user_roles
from app.services.field_notifications import emit_event
from app.services.notification_schedules import emit_configured_event
from app.schemas.procurement import (
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    ReceiveGoodsRequest,
)
from app.services import procurement as procurement_service

router = APIRouter(prefix="/procurement", tags=["procurement"])


def purchase_order_action_urls(po_id: uuid.UUID) -> dict[str, str]:
    query = urlencode({"tab": "PURCHASE_ORDERS", "purchase_order_id": str(po_id)})
    return {
        "FINANCE": f"/finance-portal?{query}",
        "EXECUTIVE": f"/executive-portal?{query}",
        "FIELD_ADMIN": f"/field-admin-portal?{query}",
        "FIELD": f"/field-portal?{query}",
        "default": f"/finance-portal?{query}",
    }


async def is_field_supervisor(session: AsyncSession, user: User) -> bool:
    if str(user.portal_type or "").upper() == "FIELD_ADMIN":
        return True
    supervisor_role = select(Role.id).where(
        or_(Role.organization_id == user.organization_id, Role.is_system_role.is_(True)),
        func.lower(func.trim(Role.name)).in_(["supervisor", "field supervisor"]),
    )
    return bool(await session.scalar(select(user_roles.c.user_id).where(
        user_roles.c.user_id == user.id, user_roles.c.role_id.in_(supervisor_role),
    ).limit(1)))


async def portal_recipients(session: AsyncSession, organization_id: uuid.UUID, portal_types: set[str]) -> set[uuid.UUID]:
    stmt = select(User.id).where(
        User.organization_id == organization_id, User.is_active.is_(True), User.archived_at.is_(None),
        func.upper(User.portal_type).in_(portal_types),
    )
    if "FINANCE" in portal_types:
        finance_roles = select(Role.id).where(
            or_(Role.organization_id == organization_id, Role.is_system_role.is_(True)),
            func.lower(func.trim(Role.name)).in_(["finance", "accountant", "accounts payable"]),
        )
        stmt = select(User.id).where(
            User.organization_id == organization_id, User.is_active.is_(True), User.archived_at.is_(None),
            or_(func.upper(User.portal_type).in_(portal_types), User.id.in_(select(user_roles.c.user_id).where(user_roles.c.role_id.in_(finance_roles)))),
        )
    return set((await session.scalars(stmt)).all())


@router.post("/purchase-orders", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    finance_or_executive = current_user.is_superuser or str(current_user.portal_type or "").upper() in {"FINANCE", "EXECUTIVE"}
    field_supervisor = not finance_or_executive and await is_field_supervisor(session, current_user)
    if not finance_or_executive and not field_supervisor:
        raise HTTPException(status_code=403, detail="Purchase orders can only be created by Finance, Executive, or field supervisors")
    if field_supervisor:
        if not payload.project_id:
            raise HTTPException(status_code=422, detail="Select an assigned project for the purchase order")
        from app.services.field_equipment import require_project
        await require_project(session, current_user, payload.project_id)
    try:
        po = await procurement_service.create_purchase_order(
            session, current_user.organization_id, payload, actor_id=current_user.id
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    if po.status == PoStatus.WAITING_APPROVAL:
        recipients = await portal_recipients(session, current_user.organization_id, {"FINANCE", "EXECUTIVE"})
        await emit_event(session, current_user.organization_id, recipients,
            f"purchase-order:{po.id}:submitted-for-approval",
            f"Purchase order {po.po_number} for {po.currency} {po.total_amount:,.2f} was submitted by {current_user.first_name} {current_user.last_name} and requires executive approval.",
            "PROJECTS", "PURCHASE_ORDER_SUBMITTED", action_url=purchase_order_action_urls(po.id))
        await session.commit()
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
    if not current_user.is_superuser and str(current_user.portal_type or "").upper() not in {"FINANCE", "EXECUTIVE"}:
        if await is_field_supervisor(session, current_user):
            from app.services.field_equipment import assigned_project_ids
            assigned_projects = set((await session.scalars(assigned_project_ids(current_user))).all())
            orders = [po for po in orders if po.created_by_id == current_user.id or po.project_id in assigned_projects]
        else:
            orders = [po for po in orders if po.created_by_id == current_user.id]
    order_ids = [po.id for po in orders]
    linked_expense_statuses: dict[uuid.UUID, list[str]] = {}
    linked_expense_totals: dict[uuid.UUID, dict[str, float]] = {}
    expense_ids: list[uuid.UUID] = []
    if order_ids:
        payment_totals = (
            select(
                OperationalExpensePayment.expense_id.label("expense_id"),
                func.sum(OperationalExpensePayment.amount).label("paid_amount"),
            )
            .where(OperationalExpensePayment.organization_id == current_user.organization_id)
            .group_by(OperationalExpensePayment.expense_id)
            .subquery()
        )
        linked_expenses = (await session.execute(
            select(
                OperationalExpense.id,
                OperationalExpense.purchase_order_id,
                OperationalExpense.expense_number,
                OperationalExpense.total_cost,
                OperationalExpense.status,
                payment_totals.c.paid_amount,
            )
            .outerjoin(payment_totals, payment_totals.c.expense_id == OperationalExpense.id)
            .where(
                OperationalExpense.organization_id == current_user.organization_id,
                OperationalExpense.purchase_order_id.in_(order_ids),
            )
        )).all()
        expense_ids = [row.id for row in linked_expenses]
        payment_rows = (await session.scalars(
            select(OperationalExpensePayment)
            .where(
                OperationalExpensePayment.organization_id == current_user.organization_id,
                OperationalExpensePayment.expense_id.in_(expense_ids) if expense_ids else False,
            )
            .order_by(OperationalExpensePayment.payment_date.desc(), OperationalExpensePayment.created_at.desc())
        )).all()
        payments_by_expense: dict[uuid.UUID, list[OperationalExpensePayment]] = {}
        for payment in payment_rows:
            payments_by_expense.setdefault(payment.expense_id, []).append(payment)
        payments_by_order: dict[uuid.UUID, list[dict]] = {}
        for row in linked_expenses:
            expense_id, purchase_order_id, expense_number, total_cost, expense_status, paid_amount = row
            if purchase_order_id is None:
                continue
            normalized_status = str(expense_status or "").upper()
            paid = paid_amount or 0
            if paid >= total_cost:
                state = "PAID"
            elif paid > 0:
                state = "PARTIALLY_PAID"
            elif normalized_status in {"PAID", "COMPLETED"}:
                state = "PARTIALLY_PAID"
            else:
                state = "RAISED"
            linked_expense_statuses.setdefault(purchase_order_id, []).append(state)
            totals = linked_expense_totals.setdefault(purchase_order_id, {"total": 0.0, "paid": 0.0})
            totals["total"] += float(total_cost or 0)
            totals["paid"] += float(paid)
            for payment in payments_by_expense.get(expense_id, []):
                payments_by_order.setdefault(purchase_order_id, []).append({
                    "expense_id": str(expense_id),
                    "expense_number": expense_number,
                    "id": str(payment.id),
                    "amount": float(payment.amount or 0),
                    "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
                    "receipt_name": payment.receipt_name,
                    "reference": payment.reference,
                })
    return [
        PurchaseOrderResponse.model_validate(po).model_copy(update={
            "expense_raised": po.id in linked_expense_statuses,
            "expense_total_amount": linked_expense_totals.get(po.id, {}).get("total", 0),
            "expense_paid_amount": linked_expense_totals.get(po.id, {}).get("paid", 0),
            "expense_balance_due": max(0, linked_expense_totals.get(po.id, {}).get("total", 0) - linked_expense_totals.get(po.id, {}).get("paid", 0)),
            "expense_payments": payments_by_order.get(po.id, []),
            "expense_status": (
                "PAID" if linked_expense_statuses.get(po.id) and all(value == "PAID" for value in linked_expense_statuses[po.id])
                else "PARTIALLY_PAID" if "PARTIALLY_PAID" in linked_expense_statuses.get(po.id, [])
                else "RAISED" if po.id in linked_expense_statuses else None
            ),
        })
        for po in orders
    ]


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
    if not current_user.is_superuser and str(current_user.portal_type or "").upper() not in {"FINANCE", "EXECUTIVE"} and po.created_by_id != current_user.id:
        raise HTTPException(status_code=404, detail="Purchase order not found.")
    return PurchaseOrderResponse.model_validate(po)


@router.patch("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def update_purchase_order(
    po_id: uuid.UUID,
    payload: PurchaseOrderUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    finance_or_executive = current_user.is_superuser or str(current_user.portal_type or "").upper() in {"FINANCE", "EXECUTIVE"}
    if not finance_or_executive and not await is_field_supervisor(session, current_user):
        raise HTTPException(status_code=403, detail="Only Finance, Executive, or the submitting field supervisor can edit purchase orders")
    existing = await procurement_service.get_purchase_order(session, current_user.organization_id, po_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if not finance_or_executive and (existing.created_by_id != current_user.id or existing.status not in {PoStatus.DRAFT, PoStatus.WAITING_APPROVAL}):
        raise HTTPException(status_code=409, detail="Only your drafts or purchase orders awaiting approval can be edited")
    if not finance_or_executive and payload.project_id:
        from app.services.field_equipment import require_project
        await require_project(session, current_user, payload.project_id)
    try:
        po = await procurement_service.update_purchase_order(
            session, current_user.organization_id, po_id, payload, current_user.id
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return PurchaseOrderResponse.model_validate(po)


@router.post("/purchase-orders/{po_id}/submit", response_model=PurchaseOrderResponse)
async def submit_purchase_order(
    po_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    po = await procurement_service.get_purchase_order(session, current_user.organization_id, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    portal = str(current_user.portal_type or "").upper()
    if not current_user.is_superuser and portal not in {"FINANCE", "EXECUTIVE"} and po.created_by_id != current_user.id:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status != PoStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Only a draft purchase order can be submitted")
    po.status = PoStatus.WAITING_APPROVAL
    po.updated_by_id = current_user.id
    await session.flush()
    await emit_configured_event(
        session,
        current_user.organization_id,
        "FINANCE_PURCHASE_ORDER_THRESHOLD",
        f"purchase-order:{po.id}:created",
        f"Purchase order {po.po_number} for {po.currency} {po.total_amount:,.2f} is awaiting approval.",
        po.total_amount,
        action_url=purchase_order_action_urls(po.id),
    )
    recipients = await portal_recipients(session, current_user.organization_id, {"FINANCE", "EXECUTIVE"})
    await emit_event(
        session, current_user.organization_id, recipients,
        f"purchase-order:{po.id}:submitted-for-approval",
        f"Purchase order {po.po_number} for {po.currency} {po.total_amount:,.2f} was submitted by {current_user.first_name} {current_user.last_name} and requires executive approval.",
        "PROJECTS", "PURCHASE_ORDER_SUBMITTED", action_url=purchase_order_action_urls(po.id),
    )
    await session.commit()
    return PurchaseOrderResponse.model_validate(await procurement_service.get_purchase_order(session, current_user.organization_id, po.id))


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderResponse)
async def approve_purchase_order(
    po_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    if not current_user.is_superuser and str(current_user.portal_type or "").upper() != "EXECUTIVE":
        raise HTTPException(status_code=403, detail="Only an executive can approve purchase orders")
    try:
        po = await procurement_service.approve_purchase_order(
            session, current_user.organization_id, po_id, current_user.id
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    recipients = {po.created_by_id} if po.created_by_id else set()
    recipients |= await portal_recipients(session, current_user.organization_id, {"FINANCE"})
    await emit_event(session, current_user.organization_id, recipients,
        f"purchase-order:{po.id}:approved",
        f"Purchase order {po.po_number} has been approved. An operational expense can now be submitted and linked to it.",
        "PROJECTS", "PURCHASE_ORDER_APPROVED", action_url=purchase_order_action_urls(po.id))
    await session.commit()
    return PurchaseOrderResponse.model_validate(po)


@router.post("/purchase-orders/{po_id}/attachment", response_model=PurchaseOrderResponse)
async def upload_purchase_order_attachment(
    po_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage=Depends(request_storage),
) -> PurchaseOrderResponse:
    portal = str(current_user.portal_type or "").upper()
    field_supervisor = await is_field_supervisor(session, current_user)
    if not current_user.is_superuser and portal not in {"FINANCE", "EXECUTIVE"} and not field_supervisor:
        raise HTTPException(status_code=403, detail="Only Finance, Executive, or the submitting field supervisor can upload purchase order attachments")
    po = await procurement_service.get_purchase_order(session, current_user.organization_id, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status not in {PoStatus.DRAFT, PoStatus.WAITING_APPROVAL}:
        raise HTTPException(status_code=409, detail="Attachments can only be added to drafts or before approval")
    if field_supervisor and portal not in {"FINANCE", "EXECUTIVE"} and po.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only attach files to your own purchase orders")
    data = await file.read()
    try:
        stored = await run_in_threadpool(
            storage.save,
            f"documents/{current_user.organization_id}/purchase-orders/{po.id}",
            data,
            file.filename or "purchase-order-attachment",
            file.content_type,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    if po.attachment_path:
        await run_in_threadpool(storage.delete, po.attachment_path)
    po.attachment_path = stored.relative_path
    po.attachment_file_name = stored.filename
    po.attachment_mime_type = stored.mime_type
    po.attachment_size_bytes = stored.size_bytes
    po.updated_by_id = current_user.id
    await session.commit()
    po = await procurement_service.get_purchase_order(session, current_user.organization_id, po_id)
    return PurchaseOrderResponse.model_validate(po)


@router.get("/purchase-orders/{po_id}/file")
async def download_purchase_order_attachment(
    po_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage=Depends(request_storage),
    inline: bool = Query(False),
):
    po = await procurement_service.get_purchase_order(session, current_user.organization_id, po_id)
    if not po or not po.attachment_path:
        raise HTTPException(status_code=404, detail="Purchase order attachment not found")
    privileged = current_user.is_superuser or str(current_user.portal_type or "").upper() in {"FINANCE", "EXECUTIVE"}
    field_supervisor = not privileged and await is_field_supervisor(session, current_user)
    if not privileged and not field_supervisor and po.created_by_id != current_user.id:
        raise HTTPException(status_code=404, detail="Purchase order attachment not found")
    if field_supervisor:
        if po.project_id:
            from app.services.field_equipment import require_project
            await require_project(session, current_user, po.project_id)
        elif po.created_by_id != current_user.id:
            raise HTTPException(status_code=404, detail="Purchase order attachment not found")
    try:
        path = await run_in_threadpool(storage.resolve, po.attachment_path)
    except (OSError, ValueError) as err:
        raise HTTPException(status_code=404, detail="Purchase order attachment is unavailable") from err
    return FileResponse(
        path,
        filename=po.attachment_file_name or "purchase-order-attachment",
        media_type=po.attachment_mime_type or "application/octet-stream",
        content_disposition_type="inline" if inline else "attachment",
    )

@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderResponse)
async def receive_goods(
    po_id: uuid.UUID,
    payload: ReceiveGoodsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PurchaseOrderResponse:
    privileged = current_user.is_superuser or str(current_user.portal_type or "").upper() in {"FINANCE", "EXECUTIVE"}
    field_supervisor = not privileged and await is_field_supervisor(session, current_user)
    if not privileged and not field_supervisor:
        raise HTTPException(status_code=403, detail="Only Finance, Executive, or assigned field supervisors can receive purchase order goods")
    if field_supervisor:
        existing = await procurement_service.get_purchase_order(session, current_user.organization_id, po_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        if existing.project_id:
            from app.services.field_equipment import require_project
            await require_project(session, current_user, existing.project_id)
        elif existing.created_by_id != current_user.id:
            raise HTTPException(status_code=404, detail="Purchase order not found")
    try:
        po = await procurement_service.receive_goods(
            session, current_user.organization_id, po_id, payload
        )
        return PurchaseOrderResponse.model_validate(po)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
