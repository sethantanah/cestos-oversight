"""Name-based bridge between the vendor master and legacy supplier/payee records."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Supplier
from app.models.operational_logs import FuelSupplier, OperationalPayee
from app.services.counters import next_business_number


async def next_supplier_number(session: AsyncSession, organization_id: uuid.UUID) -> str:
    while True:
        candidate = await next_business_number(session, organization_id, "supplier")
        exists = await session.scalar(select(Supplier.id).where(
            Supplier.organization_id == organization_id,
            Supplier.supplier_number == candidate,
        ))
        if exists is None:
            return candidate


async def ensure_vendor(
    session: AsyncSession,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    name: str,
    *,
    phone: str | None = None,
    bank_account_details: str | None = None,
    payment_method: str | None = None,
    bank_account_type: str | None = None,
) -> Supplier | None:
    clean_name = name.strip()
    if not clean_name:
        return None
    row = await session.scalar(
        select(Supplier).where(
            Supplier.organization_id == organization_id,
            func.lower(func.trim(Supplier.name)) == clean_name.lower(),
        )
    )
    if row is None:
        row = Supplier(
            organization_id=organization_id,
            created_by_id=actor_id,
            name=clean_name,
            supplier_number=await next_supplier_number(session, organization_id),
            phone=phone,
            bank_account_details=bank_account_details,
            payment_method=payment_method,
            bank_account_type=bank_account_type,
        )
        session.add(row)
    else:
        row.is_active = True
        row.archived_at = None
        if not row.supplier_number:
            row.supplier_number = await next_supplier_number(session, organization_id)
        if phone and not row.phone:
            row.phone = phone
        if bank_account_details and not row.bank_account_details:
            row.bank_account_details = bank_account_details
        if payment_method and not row.payment_method:
            row.payment_method = payment_method
        if bank_account_type and not row.bank_account_type:
            row.bank_account_type = bank_account_type

    legacy_supplier = await session.scalar(
        select(FuelSupplier).where(
            FuelSupplier.organization_id == organization_id,
            func.lower(func.trim(FuelSupplier.name)) == clean_name.lower(),
        )
    )
    if legacy_supplier is None:
        session.add(FuelSupplier(
            organization_id=organization_id,
            created_by_id=actor_id,
            name=clean_name,
        ))

    payee = await session.scalar(
        select(OperationalPayee).where(
            OperationalPayee.organization_id == organization_id,
            func.lower(func.trim(OperationalPayee.name)) == clean_name.lower(),
        )
    )
    if payee is None:
        session.add(OperationalPayee(
            organization_id=organization_id,
            created_by_id=actor_id,
            name=clean_name,
            phone=phone,
            bank_account_details=bank_account_details,
            payment_method=payment_method,
        ))
    else:
        payee.is_active = True
        if phone and not payee.phone:
            payee.phone = phone
        if bank_account_details and not payee.bank_account_details:
            payee.bank_account_details = bank_account_details
        if payment_method and not payee.payment_method:
            payee.payment_method = payment_method
    return row
