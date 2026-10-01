"""Finance vendor master shared with procurement and expense submissions."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import User
from app.models.inventory import Supplier
from app.models.operational_logs import FuelSupplier, OperationalExpense, OperationalPayee
from app.models.role import Permission, role_permissions, user_roles
from app.models.role import Role
from app.services.vendors import ensure_vendor, next_supplier_number

router = APIRouter(prefix="/finance/vendors", tags=["Finance vendors"])


class VendorInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    supplier_number: str | None = Field(default=None, max_length=50)
    bank_account_type: str | None = Field(default=None, pattern="^(SPARE_PART|FUEL|FOREIGN_PURCHASE|SERVICE_RENDERED|TRANSPORTATION|TELEPHONY_EXPENSES|INTERNET_EXPENSES|CAR_RENTAL_EXPENSES|EQUIPMENT_RENTAL_EXPENSES|FUEL_OIL|REPAIRS_AND_MAINTENANCE|PROFESSIONAL_FEES|LEGAL_SERVICES|ADMINISTRATION_SERVICES|RENT_EXPENSE|DRILL_CONSUMABLES|DRILL_CONSUMBLES|BUILDING_SUPPLIES|GENERATOR_MAINTENANCE|PLUMBING|ELECTRICAL|UTILITIES|GENERATOR|COMMUNITY_DEVELOPMENT)$")
    payment_method: str | None = Field(default=None, pattern="^(BANK_TRANSFER|MOBILE_MONEY|CASH)$")
    bank_account_details: str | None = Field(default=None, max_length=1000)


async def require_finance(session: AsyncSession, actor: User) -> None:
    if actor.is_superuser or str(actor.portal_type or "").upper() == "FINANCE":
        return
    finance_roles = select(Role.id).where(
        (Role.organization_id == actor.organization_id) | Role.is_system_role.is_(True),
        func.lower(Role.name).in_(["finance", "accountant", "accounts payable"]),
    )
    permission_roles = select(role_permissions.c.role_id).join(
        Permission, Permission.id == role_permissions.c.permission_id
    ).where(Permission.code.in_({"finance.expenses.manage", "operational_expenses.manage"}))
    authorized_roles = select(Role.id).where(
        (Role.organization_id == actor.organization_id) | Role.is_system_role.is_(True),
        Role.id.in_(permission_roles),
    )
    if await session.scalar(select(user_roles.c.user_id).where(
        user_roles.c.user_id == actor.id,
        user_roles.c.role_id.in_(finance_roles.union(authorized_roles)),
    ).limit(1)):
        return
    raise HTTPException(403, "Finance vendor access is required")


def vendor_read(row: Supplier) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "supplier_number": row.supplier_number,
        "bank_account_type": row.bank_account_type,
        "payment_method": row.payment_method,
        "bank_account_details": row.bank_account_details,
        "phone": row.phone,
        "email": row.email,
        "contact_name": row.contact_name,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def sync_legacy_rows(session: AsyncSession, org_id: uuid.UUID, actor_id: uuid.UUID, name: str, phone: str | None = None, bank_details: str | None = None, payment_method: str | None = None) -> None:
    clean_name = name.strip()
    fuel_supplier = await session.scalar(select(FuelSupplier).where(
        FuelSupplier.organization_id == org_id,
        func.lower(func.trim(FuelSupplier.name)) == clean_name.lower(),
    ))
    if not fuel_supplier:
        session.add(FuelSupplier(organization_id=org_id, created_by_id=actor_id, name=clean_name))
    payee = await session.scalar(select(OperationalPayee).where(
        OperationalPayee.organization_id == org_id,
        func.lower(func.trim(OperationalPayee.name)) == clean_name.lower(),
    ))
    if not payee:
        session.add(OperationalPayee(
            organization_id=org_id, created_by_id=actor_id, name=clean_name,
            phone=phone, bank_account_details=bank_details, payment_method=payment_method,
        ))
    else:
        payee.is_active = True
        if phone:
            payee.phone = phone
        payee.bank_account_details = bank_details
        payee.payment_method = payment_method


@router.get("")
async def list_vendors(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    await require_finance(session, actor)
    rows = await session.scalars(select(Supplier).where(
        Supplier.organization_id == actor.organization_id,
        Supplier.is_active.is_(True),
        Supplier.archived_at.is_(None),
    ).order_by(Supplier.name))
    return [vendor_read(row) for row in rows]


@router.post("", status_code=201)
async def create_vendor(body: VendorInput, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    await require_finance(session, actor)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Business name is required")
    row = await session.scalar(select(Supplier).where(
        Supplier.organization_id == actor.organization_id,
        func.lower(func.trim(Supplier.name)) == name.lower(),
    ))
    data = body.model_dump()
    data["name"] = name
    data["supplier_number"] = data.get("supplier_number") or None
    for key in ("bank_account_type", "payment_method", "bank_account_details"):
        data[key] = data.get(key) or None
    number = data.get("supplier_number")
    if number:
        number_owner = await session.scalar(select(Supplier.id).where(
            Supplier.organization_id == actor.organization_id,
            Supplier.supplier_number == number,
            *([Supplier.id != row.id] if row else []),
        ))
        if number_owner:
            raise HTTPException(409, "That supplier number is already in use")
    if row is None:
        row = Supplier(
            organization_id=actor.organization_id,
            created_by_id=actor.id,
            supplier_number=data.pop("supplier_number") or await next_supplier_number(session, actor.organization_id),
            **data,
        )
        session.add(row)
    else:
        for key, value in data.items():
            if value is not None:
                setattr(row, key, value)
        row.is_active = True
        row.archived_at = None
    await ensure_vendor(session, actor.organization_id, actor.id, name, phone=row.phone, bank_account_details=row.bank_account_details, payment_method=row.payment_method, bank_account_type=row.bank_account_type)
    await sync_legacy_rows(session, actor.organization_id, actor.id, name, row.phone, row.bank_account_details, row.payment_method)
    await session.commit()
    await session.refresh(row)
    return vendor_read(row)


@router.patch("/{vendor_id}")
async def update_vendor(vendor_id: uuid.UUID, body: VendorInput, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    await require_finance(session, actor)
    row = await session.scalar(select(Supplier).where(
        Supplier.id == vendor_id,
        Supplier.organization_id == actor.organization_id,
        Supplier.archived_at.is_(None),
    ).with_for_update())
    if not row:
        raise HTTPException(404, "Vendor not found")
    old_name = row.name
    data = body.model_dump()
    data["name"] = body.name.strip()
    data["supplier_number"] = data.get("supplier_number") or None
    for key in ("bank_account_type", "payment_method", "bank_account_details"):
        data[key] = data.get(key) or None
    if not data["name"]:
        raise HTTPException(422, "Business name is required")
    duplicate = await session.scalar(select(Supplier.id).where(
        Supplier.organization_id == actor.organization_id,
        Supplier.id != row.id,
        func.lower(func.trim(Supplier.name)) == data["name"].lower(),
        Supplier.archived_at.is_(None),
    ))
    if duplicate:
        raise HTTPException(409, "A vendor with this business name already exists")
    if data.get("supplier_number"):
        number_owner = await session.scalar(select(Supplier.id).where(
            Supplier.organization_id == actor.organization_id,
            Supplier.id != row.id,
            Supplier.supplier_number == data["supplier_number"],
        ))
        if number_owner:
            raise HTTPException(409, "That supplier number is already in use")
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_by_id = actor.id
    if old_name.strip().lower() != row.name.lower():
        for model, column in ((FuelSupplier, FuelSupplier.name), (OperationalPayee, OperationalPayee.name)):
            records = await session.scalars(select(model).where(
                model.organization_id == actor.organization_id,
                func.lower(func.trim(column)) == old_name.strip().lower(),
            ).with_for_update())
            for record in records:
                record.name = row.name
        expenses = await session.scalars(select(OperationalExpense).where(
            OperationalExpense.organization_id == actor.organization_id,
            func.lower(func.trim(OperationalExpense.pay_to_name)) == old_name.strip().lower(),
        ))
        for expense in expenses:
            expense.pay_to_name = row.name
        await sync_legacy_rows(session, actor.organization_id, actor.id, row.name, row.phone, row.bank_account_details, row.payment_method)
    else:
        await sync_legacy_rows(session, actor.organization_id, actor.id, row.name, row.phone, row.bank_account_details, row.payment_method)
    await session.commit()
    await session.refresh(row)
    return vendor_read(row)
