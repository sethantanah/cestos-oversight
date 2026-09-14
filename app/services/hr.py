import calendar
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models import Employee, RefreshToken, User
from app.models.employee import EmployeeDocument
from app.models.hr import ContractAlertRule, EmailDelivery, Notification, PasswordSetup
from app.services.audit import record_audit


async def employee_in_org(
    session: AsyncSession, actor: User, employee_id: uuid.UUID, lock: bool = False
) -> Employee:
    query = select(Employee).where(
        Employee.id == employee_id, Employee.organization_id == actor.organization_id
    )
    if lock:
        query = query.with_for_update()
    employee = await session.scalar(query)
    if employee is None:
        raise NotFoundError("Employee not found")
    return employee


async def link_account(session: AsyncSession, actor: User, employee: Employee) -> None:
    raw_email = employee.work_email or employee.personal_email
    if not raw_email:
        return
    email = raw_email.lower().strip()
    employee.work_email = email

    # Serialize employee-to-account matching, including simultaneous employee creation.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"account:{actor.organization_id}:{email}"},
    )
    user = await session.scalar(
        select(User)
        .where(User.organization_id == actor.organization_id, User.email == email)
        .with_for_update()
    )
    if user:
        if not user.is_active or user.archived_at:
            user.is_active = True
            user.archived_at = None
        if user.is_superuser and not actor.is_superuser:
            raise ForbiddenError("Only a superadmin can link a superadmin account")
        linked = await session.scalar(
            select(Employee.id).where(Employee.user_id == user.id, Employee.id != employee.id)
        )
        if linked:
            raise ConflictError("This account is already linked to another employee")
    else:
        user = User(
            organization_id=actor.organization_id,
            email=email,
            first_name=employee.first_name,
            last_name=employee.last_name,
            password_hash=await run_in_threadpool(hash_password, secrets.token_urlsafe(48)),
            setup_required=True,
            roles=[],
        )
        session.add(user)
        await session.flush()

    employee.user_id = user.id
    employee.updated_at = datetime.now(UTC)

    # Queue password reset / setup email for the associated user
    session.add(
        EmailDelivery(
            organization_id=actor.organization_id,
            recipient_id=user.id,
            kind="SETUP",
            message="Set up your Cestos account password",
            next_attempt_at=datetime.now(UTC),
        )
    )

    record_audit(
        session,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action="employee.account_linked",
        entity_type="employee",
        entity_id=employee.id,
        new_values={"user_id": str(user.id), "email": email},
    )


async def sync_all_users_and_profiles(session: AsyncSession) -> int:
    """Sync all unlinked employee profiles with matching user accounts across organizations."""
    employees = (await session.scalars(select(Employee).where(Employee.user_id.is_(None)))).all()
    count = 0
    for emp in employees:
        raw_email = emp.work_email or emp.personal_email
        if not raw_email:
            continue
        email = raw_email.lower().strip()
        user = await session.scalar(
            select(User).where(
                User.organization_id == emp.organization_id,
                User.email == email,
            )
        )
        if user:
            emp.user_id = user.id
            emp.work_email = email
            count += 1
    if count > 0:
        await session.commit()
    return count



async def invalidate_account(session: AsyncSession, user: User) -> None:
    user.token_version += 1
    user.setup_required = True
    user.password_hash = await run_in_threadpool(hash_password, secrets.token_urlsafe(48))
    now = datetime.now(UTC)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.execute(
        update(PasswordSetup)
        .where(PasswordSetup.user_id == user.id, PasswordSetup.used_at.is_(None))
        .values(used_at=now)
    )
    await session.execute(
        update(EmailDelivery)
        .where(
            EmailDelivery.recipient_id == user.id,
            EmailDelivery.kind == "SETUP",
            EmailDelivery.status == "PENDING",
        )
        .values(status="CANCELLED")
    )
    session.add(
        EmailDelivery(
            organization_id=user.organization_id,
            recipient_id=user.id,
            kind="SETUP",
            message="Reset your Cestos password",
            next_attempt_at=now,
        )
    )


def reminder_date(expiry: date, value: int, unit: str) -> date:
    if unit == "DAYS":
        return expiry - timedelta(days=value)
    if unit == "WEEKS":
        return expiry - timedelta(weeks=value)
    months = expiry.year * 12 + expiry.month - 1 - value
    year, month = divmod(months, 12)
    if year < 1:
        return date.min
    return date(year, month + 1, min(expiry.day, calendar.monthrange(year, month + 1)[1]))


async def generate_alerts(
    session: AsyncSession, organization_id: uuid.UUID | None = None, today: date | None = None
) -> int:
    today = today or datetime.now(UTC).date()
    # One scheduler transaction at a time; unique delivery keys also guard manual runs.
    if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(63208144)")):
        return 0
    query = select(ContractAlertRule).where(ContractAlertRule.is_active.is_(True))
    if organization_id:
        query = query.where(ContractAlertRule.organization_id == organization_id)
    rules = (await session.scalars(query)).all()
    total = 0
    for rule in rules:
        document_query = (
            select(EmployeeDocument, Employee)
            .join(Employee, Employee.id == EmployeeDocument.employee_id)
            .where(
                EmployeeDocument.organization_id == rule.organization_id,
                Employee.organization_id == rule.organization_id,
                EmployeeDocument.document_type == "EMPLOYMENT_CONTRACT",
                EmployeeDocument.is_active.is_(True),
                EmployeeDocument.verification_status != "REJECTED",
                EmployeeDocument.expiry_date.is_not(None),
                Employee.is_active.is_(True),
            )
        )
        if rule.employee_id:
            document_query = document_query.where(Employee.id == rule.employee_id)
        for document, employee in (await session.execute(document_query)).all():
            if reminder_date(document.expiry_date, rule.lead_value, rule.lead_unit) > today:
                continue
            for recipient_id in set(rule.recipient_ids):
                user = await session.scalar(
                    select(User).where(
                        User.id == uuid.UUID(recipient_id),
                        User.organization_id == rule.organization_id,
                        User.is_active.is_(True),
                        User.archived_at.is_(None),
                    )
                )
                if not user:
                    continue
                message = (
                    f"Contract for {employee.first_name} {employee.last_name} "
                    f"({employee.employee_number}) expires on {document.expiry_date.isoformat()}."
                )
                created = await session.scalar(
                    insert(Notification)
                    .values(
                        id=uuid.uuid4(),
                        organization_id=rule.organization_id,
                        rule_id=rule.id,
                        document_id=document.id,
                        expiry_date=document.expiry_date,
                        recipient_id=user.id,
                        message=message,
                    )
                    .on_conflict_do_nothing()
                    .returning(Notification.id)
                )
                if created:
                    total += 1
                    session.add(
                        EmailDelivery(
                            organization_id=rule.organization_id,
                            recipient_id=user.id,
                            kind="ALERT",
                            message=message,
                            next_attempt_at=datetime.now(UTC),
                        )
                    )
    await session.commit()
    return total
