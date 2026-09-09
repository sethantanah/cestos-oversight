import uuid
from datetime import UTC, date, datetime
from typing import Any, NoReturn

import structlog
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_current_active_user, require_permission, scoped_roles
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.security import hash_password, token_hash
from app.db.session import get_session
from app.models import Employee, User
from app.models.employee import (
    LeaveRequest,
    EmployeeAssignment,
    EmployeeDocument,
    EmployeeEmergencyContact,
    EmployeeLicense,
    EmployeeQualification,
    EmployeeTrainingRecord,
)
from app.models.hr import ContractAlertRule, EmailDelivery, Notification, PasswordSetup, Salary
from app.schemas.employee import (EmergencyContactCreate, EmergencyContactUpdate, TimeLogCreate, TimeLogRead, LeaveRequestCreate, LeaveRequestRead)
from app.schemas.hr import (
    AccountEmail,
    AlertRuleCreate,
    AlertRuleRead,
    PasswordReset,
    SalaryCreate,
    SalaryEnd,
    SalaryRead,
    SelfEmergencyContact,
    SelfProfileUpdate,
)
from app.services.audit import record_audit
from app.services.hr import employee_in_org, generate_alerts, invalidate_account, link_account
from app.services.workforce import DocumentService, EmergencyContactService, TimeLogService, LeaveRequestService

router = APIRouter(prefix="/hr", tags=["HR accounts, compensation and reminders"])


async def superadmin(user: User = Depends(get_current_active_user)) -> User:
    if not user.is_superuser:
        raise ForbiddenError("Only superadmins can manage account identity")
    return user


def audit(session: AsyncSession, actor: User, action: str, entity_id: uuid.UUID) -> None:
    record_audit(
        session,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action=action,
        entity_type="hr",
        entity_id=entity_id,
    )


@router.get("/employees/{employee_id}/salaries", response_model=list[SalaryRead])
async def salaries(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.salary.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    await employee_in_org(session, actor, employee_id)
    return (
        await session.scalars(
            select(Salary)
            .where(
                Salary.organization_id == actor.organization_id, Salary.employee_id == employee_id
            )
            .order_by(Salary.start_date.desc())
        )
    ).all()


@router.post("/employees/{employee_id}/salaries", response_model=SalaryRead, status_code=201)
async def add_salary(
    employee_id: uuid.UUID,
    body: SalaryCreate,
    actor: User = Depends(require_permission("employees.salary.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    await employee_in_org(session, actor, employee_id, lock=True)
    query = select(Salary.id).where(
        Salary.organization_id == actor.organization_id,
        Salary.employee_id == employee_id,
        or_(Salary.end_date.is_(None), Salary.end_date >= body.start_date),
    )
    if body.end_date:
        query = query.where(Salary.start_date <= body.end_date)
    if await session.scalar(query):
        raise ConflictError("Salary periods cannot overlap. End the previous salary first.")
    row = Salary(
        organization_id=actor.organization_id,
        employee_id=employee_id,
        created_by_id=actor.id,
        **body.model_dump(),
    )
    session.add(row)
    await session.flush()
    audit(session, actor, "salary.created", row.id)
    await session.commit()
    return row


@router.post("/salaries/{salary_id}/end", response_model=SalaryRead)
async def end_salary(
    salary_id: uuid.UUID,
    body: SalaryEnd,
    actor: User = Depends(require_permission("employees.salary.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await session.scalar(
        select(Salary).where(
            Salary.id == salary_id, Salary.organization_id == actor.organization_id
        )
    )
    if not row:
        raise NotFoundError("Salary not found")
    await employee_in_org(session, actor, row.employee_id, lock=True)
    await session.refresh(row)
    if row.end_date is not None:
        raise ConflictError("This salary period is already closed")
    if body.end_date < row.start_date:
        raise ValidationError("End date must follow start date")
    row.end_date = body.end_date
    audit(session, actor, "salary.ended", row.id)
    await session.commit()
    return row


async def validate_rule(session: AsyncSession, actor: User, body: AlertRuleCreate) -> None:
    if body.employee_id:
        await employee_in_org(session, actor, body.employee_id)
    for recipient in set(body.recipient_ids):
        if not await session.scalar(
            select(User.id).where(
                User.id == recipient,
                User.organization_id == actor.organization_id,
                User.is_active.is_(True),
                User.archived_at.is_(None),
            )
        ):
            raise ValidationError("Recipients must be active users in this organization")


@router.get("/alert-rules", response_model=list[AlertRuleRead])
async def rules(
    actor: User = Depends(require_permission("employees.alerts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return (
        await session.scalars(
            select(ContractAlertRule)
            .where(ContractAlertRule.organization_id == actor.organization_id)
            .order_by(ContractAlertRule.created_at)
        )
    ).all()


@router.post("/alert-rules", response_model=AlertRuleRead, status_code=201)
async def add_rule(
    body: AlertRuleCreate,
    actor: User = Depends(require_permission("employees.alerts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    await validate_rule(session, actor, body)
    row = ContractAlertRule(organization_id=actor.organization_id, **body.model_dump(mode="json"))
    if body.employee_id:
        row.employee_id = body.employee_id
    session.add(row)
    await session.flush()
    audit(session, actor, "contract_alert.created", row.id)
    await session.commit()
    return row


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleRead)
async def edit_rule(
    rule_id: uuid.UUID,
    body: AlertRuleCreate,
    actor: User = Depends(require_permission("employees.alerts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await session.scalar(
        select(ContractAlertRule)
        .where(
            ContractAlertRule.id == rule_id,
            ContractAlertRule.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not row:
        raise NotFoundError("Alert rule not found")
    await validate_rule(session, actor, body)
    for key, value in body.model_dump().items():
        setattr(row, key, [str(x) for x in value] if key == "recipient_ids" else value)
    audit(session, actor, "contract_alert.updated", row.id)
    await session.commit()
    return row


@router.post("/alert-rules/run")
async def run_rules(
    actor: User = Depends(require_permission("employees.alerts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return {"notifications_created": await generate_alerts(session, actor.organization_id)}


@router.get("/notifications")
async def notifications(
    actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)
) -> Any:
    rows = (
        await session.scalars(
            select(Notification)
            .where(
                Notification.organization_id == actor.organization_id,
                Notification.recipient_id == actor.id,
            )
            .order_by(Notification.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        {"id": row.id, "message": row.message, "created_at": row.created_at, "read_at": row.read_at}
        for row in rows
    ]


@router.post("/notifications/{notification_id}/read")
async def read_notification(
    notification_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.organization_id == actor.organization_id,
            Notification.recipient_id == actor.id,
        )
    )
    if not row:
        raise NotFoundError("Notification not found")
    row.read_at = datetime.now(UTC)
    await session.commit()
    return {"status": "read"}


@router.get("/email-deliveries")
async def email_deliveries(
    request: Request,
    actor: User = Depends(require_permission("employees.alerts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    rows = (
        await session.scalars(
            select(EmailDelivery)
            .where(EmailDelivery.organization_id == actor.organization_id)
            .order_by(EmailDelivery.created_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "smtp_configured": bool(
            request.app.state.settings.smtp_host and request.app.state.settings.smtp_from
        ),
        "items": [
            {
                "id": row.id,
                "recipient_id": row.recipient_id,
                "kind": row.kind,
                "status": row.status,
                "attempts": row.attempts,
                "last_error": row.last_error,
            }
            for row in rows
        ],
    }


@router.post("/email-deliveries/{delivery_id}/retry")
async def retry_delivery(
    delivery_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.alerts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await session.scalar(
        select(EmailDelivery)
        .where(
            EmailDelivery.id == delivery_id, EmailDelivery.organization_id == actor.organization_id
        )
        .with_for_update()
    )
    if not row:
        raise NotFoundError("Delivery not found")
    if row.status != "FAILED":
        raise ConflictError("Only failed deliveries can be retried")
    row.status = "PENDING"
    row.attempts = 0
    row.next_attempt_at = datetime.now(UTC)
    await session.commit()
    return {"status": "queued"}


@router.get("/employees/{employee_id}/account")
async def account(
    employee_id: uuid.UUID,
    actor: User = Depends(superadmin),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await employee_in_org(session, actor, employee_id)
    user = await session.get(User, employee.user_id) if employee.user_id else None
    return {
        "user_id": user.id if user else None,
        "email": user.email if user else None,
        "setup_required": user.setup_required if user else None,
    }


@router.post("/employees/{employee_id}/account/link")
async def link_existing(
    employee_id: uuid.UUID,
    actor: User = Depends(superadmin),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await employee_in_org(session, actor, employee_id, lock=True)
    if employee.user_id:
        raise ConflictError("Employee is already linked")
    if not (employee.work_email or employee.personal_email):
        raise ValidationError("Set an employee email first")
    await link_account(session, actor, employee)
    await session.commit()
    return {"status": "linked"}


@router.post("/employees/{employee_id}/account/reset")
async def reset_account(
    employee_id: uuid.UUID,
    actor: User = Depends(superadmin),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await employee_in_org(session, actor, employee_id, lock=True)
    user = await session.scalar(
        select(User)
        .where(User.id == employee.user_id, User.organization_id == actor.organization_id)
        .with_for_update()
    )
    if not user:
        raise NotFoundError("Linked account not found")
    await invalidate_account(session, user)
    audit(session, actor, "account.reset_requested", user.id)
    await session.commit()
    return {"status": "setup email queued; existing sessions revoked"}


@router.put("/employees/{employee_id}/account/email")
async def change_email(
    employee_id: uuid.UUID,
    body: AccountEmail,
    actor: User = Depends(superadmin),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await employee_in_org(session, actor, employee_id, lock=True)
    user = await session.scalar(
        select(User)
        .where(User.id == employee.user_id, User.organization_id == actor.organization_id)
        .with_for_update()
    )
    if not user:
        raise NotFoundError("Linked account not found")
    email = str(body.email).lower()
    if await session.scalar(
        select(User.id).where(
            User.organization_id == actor.organization_id, User.email == email, User.id != user.id
        )
    ):
        raise ConflictError("Email belongs to another account; identities will not be merged")
    if await session.scalar(
        select(Employee.id).where(
            Employee.organization_id == actor.organization_id,
            Employee.id != employee.id,
            or_(Employee.work_email == email, Employee.personal_email == email),
        )
    ):
        raise ConflictError("Email belongs to another employee")
    old_email = user.email
    user.email = email
    if employee.work_email == old_email:
        employee.work_email = email
    elif employee.personal_email == old_email:
        employee.personal_email = email
    await invalidate_account(session, user)
    audit(session, actor, "account.email_changed", user.id)
    await session.commit()
    return {"status": "email changed; reset queued; existing sessions revoked"}


@router.post("/password-reset")
async def complete_reset(body: PasswordReset, session: AsyncSession = Depends(get_session)) -> Any:
    def reject(reason: str) -> NoReturn:
        # Never log the token, its hash, or the submitted password.
        structlog.get_logger().warning(
            "password_reset_rejected",
            reason=reason,
            token_length=len(body.token.get_secret_value()),
        )
        message = (
            "This setup link has already been used or replaced by a newer reset. "
            "Open the most recent reset email and use the link in that message."
            if reason == "token_used_or_replaced"
            else "Invalid or expired setup link"
        )
        raise AuthenticationError(message)

    setup = await session.scalar(
        select(PasswordSetup).where(
            PasswordSetup.token_hash == token_hash(body.token.get_secret_value())
        )
    )
    now = datetime.now(UTC)
    if not setup:
        reject("token_not_found")
    if setup.used_at:
        reject("token_used_or_replaced")
    if setup.expires_at <= now:
        reject("token_expired")
    user = await session.scalar(
        select(User)
        .where(User.id == setup.user_id, User.organization_id == setup.organization_id)
        .with_for_update()
    )
    if not user:
        reject("account_not_found")
    if not user.is_active or user.archived_at:
        reject("account_inactive")
    if not user.setup_required:
        reject("setup_already_completed")
    await session.refresh(setup, with_for_update=True)
    if setup.used_at or setup.expires_at <= now:
        reject("token_invalidated_during_submission")
    from app.services.organization import require_active_organization

    await require_active_organization(session, user.organization_id)
    user.password_hash = await run_in_threadpool(hash_password, body.password.get_secret_value())
    user.setup_required = False
    user.token_version += 1
    setup.used_at = now
    audit(session, user, "account.password_set", user.id)
    await session.commit()
    return {"status": "Password set. Sign in with your email and new password."}


async def own_employee(session: AsyncSession, actor: User, lock: bool = False) -> Employee:
    query = select(Employee).where(
        Employee.user_id == actor.id,
        Employee.organization_id == actor.organization_id,
        Employee.is_active.is_(True),
        Employee.archived_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    employee = await session.scalar(query)
    if not employee:
        raise NotFoundError("No active employee profile is linked to your account")
    return employee


@router.get("/me")
async def my_profile(
    actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)
) -> Any:
    employee = await own_employee(session, actor)
    fields = (
        "employee_number first_name middle_name last_name preferred_name gender date_of_birth "
        "nationality marital_status personal_email work_email primary_phone secondary_phone "
        "residential_address city county_or_region country department job_title employment_type "
        "employment_status hire_date probation_end_date confirmation_date contract_start_date "
        "contract_end_date"
    ).split()
    data = {key: getattr(employee, key) for key in fields}
    # Explicit allowlists: no HR notes, family records, other users, or audit history.
    resources: dict[str, tuple[Any, str]] = {
        "contracts": (
            EmployeeDocument,
            "id title document_type issue_date expiry_date file_name verification_status",
        ),
        "emergency_contacts": (
            EmployeeEmergencyContact,
            "id full_name relationship primary_phone secondary_phone email address is_primary",
        ),
        "salaries": (Salary, "amount currency pay_period start_date end_date"),
        "assignments": (
            EmployeeAssignment,
            "assignment_number start_date end_date status role_on_project",
        ),
        "qualifications": (
            EmployeeQualification,
            "qualification_name qualification_type institution completion_date",
        ),
        "training": (
            EmployeeTrainingRecord,
            "training_name provider completion_date expiry_date status",
        ),
        "licenses": (EmployeeLicense, "license_number license_type expiry_date status"),
    }
    for name, (model, columns) in resources.items():
        query = select(model).where(
            model.organization_id == actor.organization_id, model.employee_id == employee.id
        )
        if hasattr(model, "is_active"):
            query = query.where(model.is_active.is_(True))
        if name == "contracts":
            query = query.where(EmployeeDocument.document_type == "EMPLOYMENT_CONTRACT")
        rows = (await session.scalars(query)).all()
        data[name] = [{key: getattr(row, key, None) for key in columns.split()} for row in rows]
    return data


@router.get("/me/contracts/{document_id}/download")
async def my_contract(
    document_id: uuid.UUID,
    request: Request,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await own_employee(session, actor)
    document = await session.scalar(
        select(EmployeeDocument).where(
            EmployeeDocument.id == document_id,
            EmployeeDocument.employee_id == employee.id,
            EmployeeDocument.organization_id == actor.organization_id,
            EmployeeDocument.document_type == "EMPLOYMENT_CONTRACT",
            EmployeeDocument.is_active.is_(True),
        )
    )
    if not document:
        raise NotFoundError("Contract not found")
    path, filename, media_type = await DocumentService(session, actor).download(
        employee.id, document.id, request.app.state.storage
    )
    return FileResponse(
        path, filename=filename, media_type=media_type, headers={"Cache-Control": "no-store"}
    )


@router.get("/access")
async def access(
    actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)
) -> Any:
    codes = {permission.code for role in scoped_roles(actor) for permission in role.permissions}
    return {
        "superadmin": actor.is_superuser,
        "time_log_create": actor.is_superuser or "employees.time_log.create" in codes,
        "leave_create": actor.is_superuser or "employees.leave.create" in codes,
        "leave_approve": actor.is_superuser or "employees.leave.approve" in codes,
        "leave_reject": actor.is_superuser or "employees.leave.reject" in codes,
        "workforce": actor.is_superuser or "employees.read_basic" in codes,
        "salary_read": actor.is_superuser or "employees.salary.read" in codes,
        "salary_manage": actor.is_superuser or "employees.salary.manage" in codes,
        "alerts_manage": actor.is_superuser or "employees.alerts.manage" in codes,
        "linked": bool(
            await session.scalar(
                select(Employee.id).where(
                    Employee.user_id == actor.id, Employee.organization_id == actor.organization_id
                )
            )
        ),
    }


@router.get("/alert-recipients")
async def alert_recipients(
    actor: User = Depends(require_permission("employees.alerts.manage")),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, str]]:
    rows = (
        await session.scalars(
            select(User)
            .where(
                User.organization_id == actor.organization_id,
                User.is_active.is_(True),
                User.archived_at.is_(None),
            )
            .order_by(User.first_name, User.id)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "first_name": row.first_name,
            "last_name": row.last_name,
            "email": row.email,
        }
        for row in rows
    ]


@router.patch("/me")
async def update_my_profile(
    body: SelfProfileUpdate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    employee = await own_employee(session, actor, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if changes:
        for key, value in changes.items():
            setattr(employee, key, value)
        employee.updated_at = datetime.now(UTC)
        employee.updated_by_id = actor.id
        record_audit(
            session,
            organization_id=actor.organization_id,
            actor_user_id=actor.id,
            action="employee.self_profile_updated",
            entity_type="employee",
            entity_id=employee.id,
            new_values={"fields": sorted(changes)},
        )
        await session.commit()
    return {"status": "Profile updated"}


async def owned_contact(
    session: AsyncSession, actor: User, contact_id: uuid.UUID
) -> EmployeeEmergencyContact:
    employee = await own_employee(session, actor, lock=True)
    contact = await session.scalar(
        select(EmployeeEmergencyContact)
        .where(
            EmployeeEmergencyContact.id == contact_id,
            EmployeeEmergencyContact.employee_id == employee.id,
            EmployeeEmergencyContact.organization_id == actor.organization_id,
            EmployeeEmergencyContact.is_active.is_(True),
            EmployeeEmergencyContact.archived_at.is_(None),
        )
        .with_for_update()
    )
    if not contact:
        raise NotFoundError("Emergency contact not found")
    return contact


@router.post("/me/emergency-contacts", status_code=201)
async def add_my_contact(
    body: SelfEmergencyContact,
    request: Request,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    employee = await own_employee(session, actor, lock=True)
    primary = await session.scalar(
        select(EmployeeEmergencyContact.id).where(
            EmployeeEmergencyContact.employee_id == employee.id,
            EmployeeEmergencyContact.organization_id == actor.organization_id,
            EmployeeEmergencyContact.is_active.is_(True),
            EmployeeEmergencyContact.is_primary.is_(True),
        )
    )
    contact = await EmergencyContactService(session, actor).create(
        employee.id,
        EmergencyContactCreate(**body.model_dump(), is_primary=primary is None),
        request,
    )
    return {"id": str(contact.id), "status": "Emergency contact added"}


@router.put("/me/emergency-contacts/{contact_id}")
async def update_my_contact(
    contact_id: uuid.UUID,
    body: SelfEmergencyContact,
    request: Request,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    await owned_contact(session, actor, contact_id)
    await EmergencyContactService(session, actor).update(
        contact_id, EmergencyContactUpdate(**body.model_dump()), request
    )
    return {"status": "Emergency contact updated"}


@router.post("/me/emergency-contacts/{contact_id}/primary")
async def primary_my_contact(
    contact_id: uuid.UUID,
    request: Request,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    await owned_contact(session, actor, contact_id)
    await EmergencyContactService(session, actor).set_primary(contact_id, request)
    return {"status": "Primary emergency contact updated"}


@router.post("/me/emergency-contacts/{contact_id}/archive")
async def archive_my_contact(
    contact_id: uuid.UUID,
    request: Request,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    contact = await owned_contact(session, actor, contact_id)
    if contact.is_primary:
        raise ConflictError("Choose another primary contact before removing this one")
    await EmergencyContactService(session, actor).archive(contact_id, request)
    return {"status": "Emergency contact archived"}


@router.get("/me/time-logs", response_model=list[TimeLogRead])
async def my_time_logs(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    employee = await own_employee(session, actor)
    return await TimeLogService(session, actor).list(employee.id)


@router.post("/me/time-logs", response_model=TimeLogRead, status_code=201)
async def log_my_time(body: TimeLogCreate, request: Request, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    employee = await own_employee(session, actor)
    return await TimeLogService(session, actor).create(employee.id, body, request)


@router.get("/me/leave-requests", response_model=list[LeaveRequestRead])
async def my_leave_requests(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    employee = await own_employee(session, actor)
    return await LeaveRequestService(session, actor).list(employee.id)


@router.post("/me/leave-requests", response_model=LeaveRequestRead, status_code=201)
async def book_my_leave(body: LeaveRequestCreate, request: Request, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    employee = await own_employee(session, actor)
    return await LeaveRequestService(session, actor).create(employee.id, body, request)


@router.post("/me/leave-requests/upload", response_model=LeaveRequestRead, status_code=201)
async def book_my_leave_with_letter(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    reason: str | None = Form(None),
    file: UploadFile = File(...),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    employee = await own_employee(session, actor)
    if end_date < start_date:
        raise ValidationError("Leave end date must be on or after start date")
    storage = request.app.state.storage
    data = await file.read(storage.max_bytes + 1)
    if not data:
        raise ValidationError("The attached file is empty")
    try:
        stored = await run_in_threadpool(
            storage.save, f"leave-letters/{actor.organization_id}/{employee.id}",
            data, file.filename or "", file.content_type,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error
    try:
        return await LeaveRequestService(session, actor).create(
            employee.id,
            LeaveRequestCreate(start_date=start_date, end_date=end_date, reason=reason,
                               attachment=stored.relative_path),
            request,
        )
    except BaseException:
        await run_in_threadpool(storage.delete, stored.relative_path)
        raise


@router.get("/leave-requests/{leave_id}/attachment")
async def download_leave_letter(
    leave_id: uuid.UUID, request: Request,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    leave = await session.scalar(select(LeaveRequest).where(
        LeaveRequest.id == leave_id, LeaveRequest.organization_id == actor.organization_id,
    ))
    if not leave:
        raise NotFoundError("Leave letter not found")
    codes = {p.code for role in scoped_roles(actor) for p in role.permissions}
    if not actor.is_superuser and not codes.intersection(
        {"employees.leave.read", "employees.leave.approve", "employees.leave.reject"}
    ):
        employee = await own_employee(session, actor)
        if employee.id != leave.employee_id:
            raise NotFoundError("Leave letter not found")
    prefix = f"leave-letters/{actor.organization_id}/{leave.employee_id}/"
    if not leave.attachment_url or not leave.attachment_url.startswith(prefix):
        raise NotFoundError("Leave letter not found")
    try:
        path = request.app.state.storage.resolve(leave.attachment_url)
    except ValueError as error:
        raise NotFoundError("Leave letter not found") from error
    if not path.is_file():
        raise NotFoundError("Leave letter not found")
    return FileResponse(path, filename=f"leave-letter{path.suffix}", media_type="application/octet-stream")
