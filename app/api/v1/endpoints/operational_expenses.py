"""Operational expense submission and finance payment workflow."""
import asyncio
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_current_active_user, request_storage
from app.db.session import get_session
from app.models import Role, User
from app.models.inventory import InventoryItem
from app.models.procurement import PoStatus, PurchaseOrder
from app.models.hr import Notification
from app.models.operational_logs import OperationalExpense, OperationalExpensePayment, OperationalPayee
from app.models.role import user_roles
from app.schemas.operational_expenses import OperationalExpenseCreate, OperationalExpenseRead, OperationalExpenseUpdate
from app.services.field_notifications import emit_event
from app.services.notification_schedules import emit_configured_event

router = APIRouter(prefix="/operational-expenses", tags=["Operational expenses"])


def expense_action_urls(expense_id: uuid.UUID, purchase_order_id: uuid.UUID | None = None) -> dict[str, str]:
    query = {"tab": "EXPENSES", "expense_id": str(expense_id)}
    po_query = {"tab": "PURCHASE_ORDERS", "purchase_order_id": str(purchase_order_id), "expense_id": str(expense_id)}
    return {
        "FINANCE": f"/finance-portal?{urlencode(query)}",
        "EXECUTIVE": f"/executive-portal?{urlencode(query)}",
        "FIELD_ADMIN": f"/field-admin-portal?{urlencode(query)}",
        "FIELD": f"/field-portal?{urlencode(po_query if purchase_order_id else query)}",
        "default": f"/field-admin-portal?{urlencode(query)}",
    }

async def is_finance(session: AsyncSession, actor: User) -> bool:
    if actor.is_superuser or actor.portal_type == "FINANCE":
        return True
    roles = select(Role.id).join(user_roles, user_roles.c.role_id == Role.id).where(
        user_roles.c.user_id == actor.id,
        or_(Role.organization_id == actor.organization_id, Role.is_system_role.is_(True)),
        func.lower(Role.name).in_(["finance", "accountant", "accounts payable"]),
    )
    return bool(await session.scalar(select(user_roles.c.user_id).where(user_roles.c.user_id == actor.id, user_roles.c.role_id.in_(roles)).limit(1)))

async def finance_recipients(session: AsyncSession, organization_id: uuid.UUID) -> set[uuid.UUID]:
    finance_role_ids = select(Role.id).where(
        or_(Role.organization_id == organization_id, Role.is_system_role.is_(True)),
        func.lower(Role.name).in_(["finance", "accountant", "accounts payable"]),
    )
    ids = set((await session.scalars(select(User.id).where(
        User.organization_id == organization_id, User.is_active.is_(True), User.archived_at.is_(None),
        or_(User.portal_type == "FINANCE", User.id.in_(select(user_roles.c.user_id).where(user_roles.c.role_id.in_(finance_role_ids)))),
    ))).all())
    return ids

@router.get("/payees")
async def list_payees(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(OperationalPayee).where(OperationalPayee.organization_id == actor.organization_id, OperationalPayee.is_active.is_(True)).order_by(OperationalPayee.name))).all()
    return rows

@router.get("")
async def list_expenses(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    finance = await is_finance(session, actor)
    query = select(OperationalExpense, User, PurchaseOrder.po_number).join(User, OperationalExpense.submitted_by_id == User.id, isouter=True).outerjoin(PurchaseOrder, OperationalExpense.purchase_order_id == PurchaseOrder.id).where(OperationalExpense.organization_id == actor.organization_id)
    if not finance:
        query = query.where(OperationalExpense.submitted_by_id == actor.id)
    records = (await session.execute(query.order_by(OperationalExpense.created_at.desc()))).all()
    expense_ids = [exp.id for exp, _, _ in records]
    payment_rows = (await session.scalars(select(OperationalExpensePayment).where(
        OperationalExpensePayment.organization_id == actor.organization_id,
        OperationalExpensePayment.expense_id.in_(expense_ids) if expense_ids else False,
    ).order_by(OperationalExpensePayment.payment_date, OperationalExpensePayment.created_at))).all()
    payments_by_expense: dict[uuid.UUID, list[OperationalExpensePayment]] = {}
    for payment in payment_rows:
        payments_by_expense.setdefault(payment.expense_id, []).append(payment)
    res = []
    for exp, submitter, purchase_order_number in records:
        data = OperationalExpenseRead.model_validate(exp).model_dump(mode="json")
        payments = payments_by_expense.get(exp.id, [])
        paid_amount = sum((p.amount for p in payments), Decimal("0"))
        # Older completion records stored a status and receipt without the
        # payment amount; require reconciliation instead of inventing a total.
        stored_status = (exp.status or "").upper()
        history_missing = not payments and stored_status in {"PAID", "COMPLETED"}
        balance_due = max(Decimal("0"), exp.total_cost - paid_amount)
        data["paid_amount"] = str(paid_amount)
        data["balance_due"] = str(balance_due)
        data["payment_history_missing"] = history_missing
        if payments:
            # Payment records are the source of truth. Repair stale statuses in
            # the API response even before the reconciliation migration runs.
            data["status"] = "COMPLETED" if balance_due == 0 else "PARTIALLY_PAID"
        elif history_missing:
            # The legacy completion has no payment amount attached, so report
            # the full balance as outstanding and flag the missing history.
            data["status"] = "PARTIALLY_PAID"
        data["payments"] = [{"id": str(p.id), "amount": str(p.amount), "payment_date": p.payment_date.isoformat(),
                              "created_at": p.created_at.isoformat() if p.created_at else None,
                              "receipt_name": p.receipt_name, "reference": p.reference, "notes": p.notes,
                              "paid_by_id": str(p.paid_by_id)} for p in payments]
        data["purchase_order_number"] = purchase_order_number
        if submitter:
            data["submitted_by_name"] = f"{submitter.first_name} {submitter.last_name}".strip()
            data["submitted_by_email"] = submitter.email
            data["submitted_by_position"] = "Operations Director" if submitter.is_superuser else f"{submitter.portal_type.replace('_', ' ').title()} Administrator"
        else:
            data["submitted_by_name"] = "Operations Staff"
            data["submitted_by_email"] = actor.email
            data["submitted_by_position"] = "Field Administrator"
        res.append(data)
    return res

@router.post("", response_model=OperationalExpenseRead, status_code=201)
async def create_expense(
    request: Request, background: BackgroundTasks,
    expense_json: str = Form(...), invoice: UploadFile = File(...),
    actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session),
    storage=Depends(request_storage),
):
    import json
    try:
        body = OperationalExpenseCreate.model_validate(json.loads(expense_json))
    except Exception as exc:
        raise HTTPException(422, "Expense details are invalid") from exc
    purchase_order = None
    if body.purchase_order_id:
        purchase_order = await session.scalar(select(PurchaseOrder).where(
            PurchaseOrder.id == body.purchase_order_id,
            PurchaseOrder.organization_id == actor.organization_id,
            PurchaseOrder.archived_at.is_(None),
        ))
        if not purchase_order:
            raise HTTPException(404, "Purchase order not found")
        if purchase_order.status != PoStatus.APPROVED:
            raise HTTPException(409, "Only an approved purchase order can be linked to an expense")
        if not await is_finance(session, actor) and purchase_order.created_by_id != actor.id:
            raise HTTPException(403, "Only the purchase order submitter can link it to an expense")
    data = await invoice.read(storage.max_bytes + 1)
    if not data:
        raise HTTPException(422, "Attach a non-empty invoice or supporting document")
    try:
        stored = await run_in_threadpool(storage.save, f"documents/{actor.organization_id}/operational-expenses", data, invoice.filename or "invoice.pdf", invoice.content_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    payee_id = body.payee_id
    if payee_id:
        payee = await session.scalar(select(OperationalPayee).where(OperationalPayee.id == payee_id, OperationalPayee.organization_id == actor.organization_id, OperationalPayee.is_active.is_(True)))
        if not payee:
            raise HTTPException(404, "Selected payee was not found")
        payee.name, payee.phone, payee.bank_account_details = body.pay_to_name, body.pay_to_phone, body.bank_account_details
    else:
        payee = await session.scalar(select(OperationalPayee).where(OperationalPayee.organization_id == actor.organization_id, func.lower(OperationalPayee.name) == body.pay_to_name.lower(), OperationalPayee.phone == body.pay_to_phone, OperationalPayee.bank_account_details == body.bank_account_details))
        if payee is None:
            payee = OperationalPayee(organization_id=actor.organization_id, created_by_id=actor.id, name=body.pay_to_name, phone=body.pay_to_phone, bank_account_details=body.bank_account_details)
            session.add(payee)
            await session.flush()
        payee_id = payee.id
    item_rows = []
    calculated = Decimal("0")
    for item in body.items:
        if item.inventory_item_id and not await session.scalar(select(InventoryItem.id).where(InventoryItem.id == item.inventory_item_id, InventoryItem.organization_id == actor.organization_id)):
            raise HTTPException(422, "An inventory item was not found in this organization")
        line_total = item.total if item.total is not None else (item.quantity * item.unit_cost).quantize(Decimal("0.01"))
        calculated += line_total
        item_rows.append({**item.model_dump(mode="json"), "total": str(line_total)})
    total = body.total_cost if body.manual_total and body.total_cost is not None else calculated
    row = OperationalExpense(
        organization_id=actor.organization_id, created_by_id=actor.id, submitted_by_id=actor.id,
        purchase_order_id=body.purchase_order_id,
        expense_number=f"OPEX-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        payee_id=payee_id, pay_to_name=body.pay_to_name, pay_to_phone=body.pay_to_phone,
        bank_account_details=body.bank_account_details, expense_date=body.expense_date,
        payment_method=body.payment_method, items=item_rows, total_cost=total, status="SUBMITTED",
        invoice_path=stored.relative_path, invoice_name=stored.filename, invoice_mime_type=stored.mime_type,
        invoice_size_bytes=stored.size_bytes, extraction_status="PENDING",
    )
    session.add(row)
    await session.flush()
    await emit_event(session, actor.organization_id, await finance_recipients(session, actor.organization_id),
        f"operational-expense:{row.id}:submitted", f"Expense {row.expense_number} was submitted to Finance by {actor.first_name} {actor.last_name} for {row.total_cost}.",
        "FINANCE", "EXPENSE_SUBMITTED_TO_FINANCE", action_url=expense_action_urls(row.id))
    await emit_configured_event(
        session,
        actor.organization_id,
        "FINANCE_OPERATIONAL_EXPENSE_THRESHOLD",
        f"operational-expense:{row.id}:threshold",
        f"Operational expense {row.expense_number} for {row.total_cost} was submitted by {actor.email or actor.id} to {row.pay_to_name}.",
        row.total_cost,
        action_url=expense_action_urls(row.id),
    )
    await emit_event(
        session, actor.organization_id, {actor.id}, f"operational-expense:{row.id}:raised",
        f"Expense {row.expense_number} was raised and submitted to Finance for {row.total_cost}.",
        "FINANCE", "EXPENSE_RAISED", action_url=expense_action_urls(row.id, row.purchase_order_id),
    )
    await session.commit()
    await session.refresh(row)
    if purchase_order:
        row.purchase_order_number = purchase_order.po_number
    background.add_task(extract_invoice_safely, request.app.state.session_factory, storage, row.id, actor.organization_id, stored.relative_path, stored.filename)
    return row

@router.patch("/{expense_id}", response_model=OperationalExpenseRead)
async def update_expense(
    expense_id: uuid.UUID, body: OperationalExpenseUpdate,
    actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(select(OperationalExpense).where(
        OperationalExpense.id == expense_id,
        OperationalExpense.organization_id == actor.organization_id,
    ).with_for_update())
    if not row or (row.submitted_by_id != actor.id and not await is_finance(session, actor)):
        raise HTTPException(404, "Expense not found")
    if row.paid_at is not None or (row.status or "").upper() in {"PAID", "COMPLETED", "PARTIALLY_PAID"}:
        raise HTTPException(409, "Expenses with recorded payments cannot be edited")
    if row.submitted_by_id != actor.id:
        raise HTTPException(403, "Only the submitter can edit this expense")
    changes = body.model_dump(exclude_unset=True)
    for field in ("pay_to_name", "expense_date", "payment_method"):
        if field in changes and changes[field] is not None:
            setattr(row, field, changes[field])
    if "total_cost" in changes and changes["total_cost"] is not None:
        row.total_cost = changes["total_cost"]
    await session.commit()
    await session.refresh(row)
    return row

async def extract_invoice_safely(session_factory, storage, expense_id, organization_id, relative_path, filename):
    """Try local document extraction without affecting expense submission or payment."""
    try:
        if not hasattr(storage, "resolve"):
            raise RuntimeError("Storage backend does not expose a local extraction path")
        path = storage.resolve(relative_path)
        from app.services.document_index import extract
        sections, warning = await asyncio.to_thread(extract, path, filename)
        text = "\n".join(section.get("text", "") for section in sections)[:100_000]
        structured = {"text_preview": text[:10000]}
        match = re.search(r"(?:invoice|receipt)\s*(?:no\.?|#|number)?\s*[:#-]?\s*([A-Z0-9/-]{3,})", text, re.I)
        if match:
            structured["reference_number"] = match.group(1)
        amount = re.search(r"(?:grand\s+total|total\s+due|amount\s+due|total)\s*[: ]\s*([A-Z]{0,3}\s?\d[\d,]*(?:\.\d{2})?)", text, re.I)
        if amount:
            try:
                structured["suggested_total"] = str(Decimal(re.sub(r"[^\d.]", "", amount.group(1))))
            except Exception:
                pass
        if warning:
            structured["extraction_note"] = warning[:500]
        async with session_factory() as session:
            row = await session.scalar(select(OperationalExpense).where(OperationalExpense.id == expense_id, OperationalExpense.organization_id == organization_id))
            if row:
                row.extracted_data = structured
                row.extraction_status = "COMPLETED"
                await session.commit()
    except Exception:
        try:
            async with session_factory() as session:
                row = await session.scalar(select(OperationalExpense).where(OperationalExpense.id == expense_id, OperationalExpense.organization_id == organization_id))
                if row:
                    row.extraction_status = "FAILED"
                    row.extracted_data = {}
                    await session.commit()
        except Exception:
            pass

@router.post("/{expense_id}/payment-receipt", response_model=OperationalExpenseRead)
async def complete_expense(expense_id: uuid.UUID, amount: Decimal = Form(...), payment_date: date = Form(...), receipt: UploadFile | None = File(default=None), reference: str | None = Form(default=None), notes: str | None = Form(default=None), actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session), storage=Depends(request_storage)):
    if not await is_finance(session, actor):
        raise HTTPException(403, "Finance access is required to complete an expense")
    row = await session.scalar(select(OperationalExpense).where(OperationalExpense.id == expense_id, OperationalExpense.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(404, "Expense not found")
    prior = (await session.scalars(select(OperationalExpensePayment).where(
        OperationalExpensePayment.expense_id == row.id,
        OperationalExpensePayment.organization_id == actor.organization_id,
    ))).all()
    paid_to_date = sum((p.amount for p in prior), Decimal("0"))
    remaining = max(Decimal("0"), row.total_cost - paid_to_date)
    if amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(422, "Payment amount can have at most two decimal places")
    if amount <= 0 or amount > remaining:
        raise HTTPException(422, f"Payment must be greater than zero and no more than the remaining balance ({remaining})")
    if receipt is not None:
        data = await receipt.read(storage.max_bytes + 1)
        if not data:
            raise HTTPException(422, "Attach a non-empty payment receipt")
        try:
            stored = await run_in_threadpool(storage.save, f"documents/{actor.organization_id}/operational-expenses/receipts", data, receipt.filename or "receipt.pdf", receipt.content_type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        receipt_path, receipt_name = stored.relative_path, stored.filename
        receipt_mime_type, receipt_size_bytes = stored.mime_type, stored.size_bytes
    elif row.receipt_path and row.receipt_name:
        receipt_path, receipt_name = row.receipt_path, row.receipt_name
        receipt_mime_type, receipt_size_bytes = row.receipt_mime_type, row.receipt_size_bytes
    else:
        raise HTTPException(422, "Attach a non-empty payment receipt")
    # Clear any stale COMPLETED state before inserting a payment. Some
    # installations may have an immediate database trigger, which would
    # otherwise inspect the legacy status before this transaction updates it.
    row.status = "PARTIALLY_PAID"
    row.paid_by_id = actor.id
    row.paid_at = datetime.now(UTC)
    row.receipt_path, row.receipt_name, row.receipt_mime_type, row.receipt_size_bytes = (
        receipt_path, receipt_name, receipt_mime_type, receipt_size_bytes
    )
    await session.flush()

    payment = OperationalExpensePayment(
        organization_id=actor.organization_id, created_by_id=actor.id, expense_id=row.id,
        amount=amount, payment_date=payment_date, receipt_path=receipt_path,
        receipt_name=receipt_name, receipt_mime_type=receipt_mime_type, receipt_size_bytes=receipt_size_bytes,
        paid_by_id=actor.id, reference=(reference or "").strip() or None, notes=(notes or "").strip() or None,
    )
    session.add(payment)
    # Persist the payment row before transitioning to COMPLETED so an
    # immediate trigger sees the final paid total when checking that status.
    await session.flush()
    paid_total = paid_to_date + amount
    balance_due = max(Decimal("0"), row.total_cost - paid_total)
    fully_paid = balance_due == 0
    row.status = "COMPLETED" if fully_paid else "PARTIALLY_PAID"
    if fully_paid:
        message = f"Your operational expense {row.expense_number} has been paid in full. The latest payment receipt is available."
        event_key = f"operational-expense:{row.id}:completed"
    else:
        message = f"Finance paid {amount} toward operational expense {row.expense_number}; remaining balance: {balance_due}."
        event_key = f"operational-expense:{row.id}:payment:{payment.id}"
    await emit_event(session, actor.organization_id, {row.submitted_by_id}, event_key, message, "FINANCE", "FINANCE_EXPENSE_PAYMENT",
        action_url=expense_action_urls(row.id, row.purchase_order_id))
    await session.commit()
    await session.refresh(row)
    data_out = OperationalExpenseRead.model_validate(row).model_dump(mode="json")
    data_out["paid_amount"] = str(paid_total)
    data_out["balance_due"] = str(balance_due)
    data_out["payments"] = [
        {"id": str(p.id), "amount": str(p.amount), "payment_date": p.payment_date.isoformat(),
         "created_at": p.created_at.isoformat() if p.created_at else None,
         "receipt_name": p.receipt_name, "reference": p.reference, "notes": p.notes, "paid_by_id": str(p.paid_by_id)}
        for p in [*prior, payment]
    ]
    return data_out


@router.get("/{expense_id}/payments/{payment_id}/receipt")
async def download_payment_receipt(expense_id: uuid.UUID, payment_id: uuid.UUID, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session), storage=Depends(request_storage)):
    expense = await session.scalar(select(OperationalExpense).where(OperationalExpense.id == expense_id, OperationalExpense.organization_id == actor.organization_id))
    can_view = bool(expense and (
        actor.id == expense.submitted_by_id
        or await is_finance(session, actor)
        or str(actor.portal_type or "").upper() == "EXECUTIVE"
    ))
    if expense and not can_view and expense.purchase_order_id:
        from app.models.procurement import PurchaseOrder
        purchase_order = await session.scalar(select(PurchaseOrder).where(
            PurchaseOrder.id == expense.purchase_order_id,
            PurchaseOrder.organization_id == actor.organization_id,
        ))
        can_view = bool(purchase_order and purchase_order.created_by_id == actor.id)
        if purchase_order and not can_view:
            from app.api.v1.endpoints.procurement import is_field_supervisor
            if await is_field_supervisor(session, actor):
                from app.services.field_equipment import assigned_project_ids
                assigned_projects = set((await session.scalars(assigned_project_ids(actor))).all())
                can_view = purchase_order.project_id in assigned_projects
    if not expense or not can_view:
        raise HTTPException(404, "Expense not found")
    payment = await session.scalar(select(OperationalExpensePayment).where(OperationalExpensePayment.id == payment_id, OperationalExpensePayment.expense_id == expense.id, OperationalExpensePayment.organization_id == actor.organization_id))
    if not payment:
        raise HTTPException(404, "Payment receipt not found")
    local = await run_in_threadpool(storage.resolve, payment.receipt_path)
    return FileResponse(local, filename=payment.receipt_name)

@router.get("/{expense_id}/files/{kind}")
async def download_expense_file(expense_id: uuid.UUID, kind: str, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session), storage=Depends(request_storage)):
    row = await session.scalar(select(OperationalExpense).where(OperationalExpense.id == expense_id, OperationalExpense.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(404, "Expense not found")
    if actor.id != row.submitted_by_id and not await is_finance(session, actor):
        raise HTTPException(404, "Expense not found")
    path, name = (row.invoice_path, row.invoice_name) if kind == "invoice" else (row.receipt_path, row.receipt_name) if kind == "receipt" else (None, None)
    if not path or not name:
        raise HTTPException(404, "File not found")
    local = await run_in_threadpool(storage.resolve, path)
    return FileResponse(local, filename=name)
