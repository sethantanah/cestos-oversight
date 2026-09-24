"""Field alerts use real SQL with a local database; SMTP is always mocked."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import (
    AssetAssignment,
    Employee,
    EmployeeAssignment,
    Organization,
    Project,
    Role,
    User,
)
from app.models.employee import EmployeeDocument, EmployeeTrainingRecord, LeaveRequest
from app.models.hr import EmailDelivery, Notification
from app.models.maintenance_hse import MaintenanceWorkOrder, WorkOrderCostLine
from app.models.operational_logs import AssetMaintenanceJob
from app.models.role import Permission, role_permissions, user_roles
from app.services.field_notifications import (
    emit_event,
    employee_recipients,
    generate_field_alerts,
    notify_assignment,
    notify_leave,
    notify_work_order,
    supervisor_recipients,
)
from app.services.notification_service import NotificationService


@compiles(JSONB, "sqlite")
def sqlite_json(element, compiler, **kw):
    return "JSON"


class AsyncAdapter:
    def __init__(self, session):
        self.session = session

    async def scalar(self, query):
        return self.session.scalar(query)

    async def scalars(self, query):
        return self.session.scalars(query)

    async def execute(self, query):
        return self.session.execute(query)

    async def get(self, model, identity):
        return self.session.get(model, identity)

    async def commit(self):
        self.session.commit()

    async def flush(self):
        self.session.flush()

    def add(self, value):
        self.session.add(value)

    def get_bind(self):
        return self.session.get_bind()


@pytest.fixture
def field_db():
    engine = create_engine("sqlite://")
    models = [
        Project,
        AssetAssignment,
        Organization,
        User,
        Role,
        Permission,
        Employee,
        EmployeeAssignment,
        EmployeeDocument,
        EmployeeTrainingRecord,
        LeaveRequest,
        Notification,
        EmailDelivery,
        AssetMaintenanceJob,
        MaintenanceWorkOrder,
        WorkOrderCostLine,
    ]
    for model in models:
        model.__table__.create(engine)
    user_roles.create(engine)
    role_permissions.create(engine)
    with Session(engine, expire_on_commit=False) as session:
        org = Organization(name="Field")
        other_org = Organization(name="Other")
        session.add_all([org, other_org])
        session.flush()

        def person(label, role=None, organization=None):
            organization = organization or org
            user = User(
                organization_id=organization.id,
                email=f"{label}@example.com",
                first_name=label,
                last_name="User",
                password_hash="test",
            )
            session.add(user)
            session.flush()
            employee = Employee(
                organization_id=organization.id,
                user_id=user.id,
                employee_number=label,
                first_name=label,
                last_name="Person",
            )
            session.add(employee)
            session.flush()
            if role:
                role_record = Role(name=role, organization_id=organization.id)
                session.add(role_record)
                session.flush()
                session.execute(user_roles.insert().values(user_id=user.id, role_id=role_record.id))
            return user, employee

        worker, employee = person("worker")
        supervisor, boss = person("boss", "Supervisor")
        manager, manager_employee = person("manager", "Manager")
        outsider, outsider_employee = person("outsider", "supervisor", other_org)
        employee.supervisor_id = boss.id
        session.commit()
        yield SimpleNamespace(
            session=session,
            db=AsyncAdapter(session),
            org=org,
            worker=worker,
            employee=employee,
            supervisor=supervisor,
            boss=boss,
            manager=manager,
            outsider=outsider,
        )
    engine.dispose()


async def test_event_is_atomic_deduplicated_and_recipient_scoped(field_db):
    f = field_db
    recipients = {f.worker.id, f.outsider.id}
    assert (
        await emit_event(
            f.db, f.org.id, recipients, "assignment:1", "Assigned", "PROJECTS", "PROJECT_ASSIGNMENT"
        )
        == 1
    )
    assert len(f.session.scalars(select(Notification)).all()) == 1
    assert len(f.session.scalars(select(EmailDelivery)).all()) == 1
    f.session.rollback()
    assert not f.session.scalars(select(Notification)).all()
    assert not f.session.scalars(select(EmailDelivery)).all()
    await emit_event(
        f.db, f.org.id, recipients, "assignment:1", "Assigned", "PROJECTS", "PROJECT_ASSIGNMENT"
    )
    await f.db.commit()
    notification = f.session.scalar(select(Notification))
    notification.read_at = datetime.now(UTC)
    notification.is_resolved = True
    await f.db.commit()
    assert (
        await emit_event(
            f.db, f.org.id, recipients, "assignment:1", "Assigned", "PROJECTS", "PROJECT_ASSIGNMENT"
        )
        == 0
    )
    assert len(f.session.scalars(select(EmailDelivery)).all()) == 1


async def test_leave_recipients_and_decision_match_email(field_db):
    f = field_db
    assert await supervisor_recipients(f.db, f.org.id, f.employee.id) == {f.supervisor.id}
    leave = LeaveRequest(
        organization_id=f.org.id,
        employee_id=f.employee.id,
        start_date=date.today(),
        end_date=date.today(),
        leave_type="Annual",
        reason="Private medical detail",
        status="PENDING",
    )
    f.session.add(leave)
    f.session.flush()
    assert await notify_leave(f.db, leave) == 1
    [alert] = f.session.scalars(select(Notification)).all()
    [mail] = f.session.scalars(select(EmailDelivery)).all()
    assert alert.recipient_id == mail.recipient_id == f.supervisor.id
    assert alert.message == mail.message
    assert "Private medical detail" not in alert.message
    leave.status = "APPROVED"
    assert await notify_leave(f.db, leave) == 1
    decision = f.session.scalar(select(EmailDelivery).where(EmailDelivery.kind == "LEAVE_DECISION"))
    assert decision.recipient_id == f.worker.id


async def test_expiry_and_overdue_alerts_stop_after_completion_and_do_not_repeat(field_db):
    f = field_db
    today = date.today()
    f.employee.contract_end_date = today + timedelta(days=6)
    work = AssetMaintenanceJob(
        organization_id=f.org.id,
        asset_id=uuid.uuid4(),
        title="Repair pump",
        maintenance_type="SERVICE",
        priority="HIGH",
        status="OPEN",
        scheduled_date=today - timedelta(days=2),
        assigned_employee_id=f.employee.id,
        cost=0,
        currency="USD",
    )
    f.session.add(work)
    f.session.commit()
    assert await generate_field_alerts(f.db, today) == 4
    assert await generate_field_alerts(f.db, today) == 0
    messages = f.session.scalars(select(EmailDelivery)).all()
    assert {mail.kind for mail in messages} == {"CONTRACT_EXPIRY", "WORK_ORDER_OVERDUE"}
    assert {mail.recipient_id for mail in messages} == {f.worker.id, f.supervisor.id}
    work.status = "COMPLETED"
    f.employee.contract_end_date = None
    f.session.commit()
    assert await generate_field_alerts(f.db, today + timedelta(days=8)) == 0


async def test_work_assignment_due_and_completed_recipients(field_db):
    f = field_db
    work = AssetMaintenanceJob(
        organization_id=f.org.id,
        asset_id=uuid.uuid4(),
        title="Service rig",
        maintenance_type="SERVICE",
        priority="HIGH",
        status="OPEN",
        scheduled_date=date.today() + timedelta(days=1),
        assigned_employee_id=f.employee.id,
        cost=0,
        currency="USD",
    )
    f.session.add(work)
    f.session.flush()
    assert await notify_work_order(f.db, work) == 1
    assert f.session.scalar(select(Notification)).recipient_id == f.worker.id
    assert await generate_field_alerts(f.db) == 1
    work.status = "COMPLETED"
    work.updated_at = datetime.now(UTC)
    assert await notify_work_order(f.db, work, "completed") == 2


async def test_inactive_or_foreign_employee_never_routes_to_a_user(field_db):
    f = field_db
    assert await employee_recipients(f.db, f.org.id, f.employee.id) == {f.worker.id}
    f.worker.is_active = False
    f.session.flush()
    assert await employee_recipients(f.db, f.org.id, f.employee.id) == set()
    assert await employee_recipients(f.db, f.outsider.organization_id, f.employee.id) == set()


async def test_inbox_actions_cannot_read_or_modify_another_recipients_alert(field_db):
    f = field_db
    await emit_event(
        f.db, f.org.id, {f.worker.id}, "private", "Personal alert", "WORKFORCE", "LEAVE_DECISION"
    )
    f.session.commit()
    notification = f.session.scalar(select(Notification))
    service = NotificationService(f.db, f.supervisor)
    assert await service.list_notifications() == ([], 0)
    for action in (service.mark_read, service.resolve_notification, service.forward_notification):
        with pytest.raises(NotFoundError):
            await action(notification.id)


async def test_mail_subject_destination_and_delivery_use_same_recipient(field_db, monkeypatch):
    from app.services import mail

    f = field_db
    f.worker.is_field_portal_only = True
    await emit_event(
        f.db,
        f.org.id,
        {f.worker.id},
        "email-link",
        "Assigned to a project",
        "PROJECTS",
        "PROJECT_ASSIGNMENT",
        action_url="/field-portal?tab=PURCHASE_ORDERS&purchase_order_id=po-test",
    )
    f.session.commit()
    captured = []
    monkeypatch.setattr(mail, "send_email", lambda *args: captured.append(args))
    settings = SimpleNamespace(
        smtp_host="test", smtp_from="test@example.com", public_base_url="https://cestos.example"
    )
    assert await mail.deliver_one(f.db, settings)
    assert captured[0][1] == f.worker.email
    assert captured[0][2] == "Cestos project assignment update"
    assert "/field-portal?tab=PURCHASE_ORDERS&amp;purchase_order_id=po-test" in captured[0][3]
    [notification] = f.session.scalars(select(Notification)).all()
    [delivery] = f.session.scalars(select(EmailDelivery)).all()
    assert notification.action_url == delivery.action_url == "/field-portal?tab=PURCHASE_ORDERS&purchase_order_id=po-test"
    assert f.session.scalar(select(EmailDelivery)).status == "SENT"


async def test_project_assignment_and_cancellation_notify_employee(field_db):
    f = field_db
    project = Project(
        organization_id=f.org.id, project_number="P-1", client_id=uuid.uuid4(), name="Drill Site"
    )
    f.session.add(project)
    f.session.flush()
    assignment = EmployeeAssignment(
        organization_id=f.org.id,
        employee_id=f.employee.id,
        project_id=project.id,
        assignment_number="A-1",
        start_date=date.today(),
        status="ACTIVE",
    )
    f.session.add(assignment)
    f.session.flush()
    assert await notify_assignment(f.db, assignment) == 1
    assert await notify_assignment(f.db, assignment) == 0
    [notification] = f.session.scalars(select(Notification)).all()
    assert notification.recipient_id == f.worker.id
    assert "Drill Site" in notification.message
    assignment.status = "CANCELLED"
    assignment.updated_at = datetime.now(UTC)
    assert await notify_assignment(f.db, assignment) == 1
    assert len(f.session.scalars(select(EmailDelivery)).all()) == 2


async def test_unassigned_overdue_work_notifies_asset_project_supervisor(field_db):
    f = field_db
    project_id, asset_id = uuid.uuid4(), uuid.uuid4()
    f.session.add(
        EmployeeAssignment(
            organization_id=f.org.id,
            employee_id=f.boss.id,
            project_id=project_id,
            assignment_number="SUP-A",
            start_date=date.today(),
            status="ACTIVE",
        )
    )
    f.session.add(
        AssetAssignment(
            organization_id=f.org.id,
            asset_id=asset_id,
            project_id=project_id,
            assignment_number="ASSET-A",
            assigned_at=datetime.now(UTC) - timedelta(days=2),
            status="ACTIVE",
        )
    )
    f.session.add(
        AssetMaintenanceJob(
            organization_id=f.org.id,
            asset_id=asset_id,
            title="Unassigned repair",
            maintenance_type="SERVICE",
            priority="HIGH",
            status="OPEN",
            currency="USD",
            cost=0,
            scheduled_date=date.today() - timedelta(days=1),
        )
    )
    f.session.commit()
    assert await generate_field_alerts(f.db) == 1
    assert f.session.scalar(select(Notification)).recipient_id == f.supervisor.id


async def test_detailed_maintenance_work_order_uses_same_reminders(field_db):
    f = field_db
    f.session.add(
        MaintenanceWorkOrder(
            organization_id=f.org.id,
            asset_id=uuid.uuid4(),
            wo_number="WO-1",
            title="Rig service",
            assigned_technician_id=f.employee.id,
            scheduled_date=date.today() - timedelta(days=1),
            status="OPEN",
        )
    )
    f.session.commit()
    assert await generate_field_alerts(f.db) == 2
    assert {row.recipient_id for row in f.session.scalars(select(Notification))} == {
        f.worker.id,
        f.supervisor.id,
    }


async def test_failed_smtp_keeps_email_queued_without_duplicating_inbox(field_db, monkeypatch):
    from app.services import mail

    f = field_db
    await emit_event(
        f.db, f.org.id, {f.worker.id}, "retry", "Task assigned", "EQUIPMENT", "WORK_ORDER_UPDATE"
    )
    f.session.commit()

    def fail(*args):
        raise OSError("SMTP unavailable")

    monkeypatch.setattr(mail, "send_email", fail)
    settings = SimpleNamespace(
        smtp_host="test", smtp_from="test@example.com", public_base_url="https://cestos.example"
    )
    assert await mail.deliver_one(f.db, settings)
    job = f.session.scalar(select(EmailDelivery))
    assert job.status == "PENDING" and job.attempts == 1
    assert len(f.session.scalars(select(Notification)).all()) == 1
    assert (
        await emit_event(
            f.db,
            f.org.id,
            {f.worker.id},
            "retry",
            "Task assigned",
            "EQUIPMENT",
            "WORK_ORDER_UPDATE",
        )
        == 0
    )


async def test_training_participant_alerts_and_scheduler_reminders_are_deduplicated(field_db):
    from app.services.field_notifications import generate_people_alerts, notify_training
    f = field_db
    today = date.today()
    course = EmployeeTrainingRecord(organization_id=f.org.id, employee_id=f.employee.id,
        training_name="Rig Safety", provider="Site Academy", start_date=today + timedelta(days=3), status="PLANNED")
    f.session.add(course)
    f.session.commit()
    assert await notify_training(f.db, course) == 1
    assert await notify_training(f.db, course) == 0
    assert await generate_people_alerts(f.db, f.org.id, today) == 1
    assert await generate_people_alerts(f.db, f.org.id, today) == 0
    alerts = f.session.scalars(select(Notification)).all()
    assert len(alerts) == 2 and {row.recipient_id for row in alerts} == {f.worker.id}
    course.status = "CANCELLED"
    course.updated_at = datetime.now(UTC)
    assert await notify_training(f.db, course, changed=True) == 1
    assert await generate_people_alerts(f.db, f.org.id, today) == 0


async def test_leave_request_notifies_hr_approver_and_decision_notifies_employee(field_db):
    f = field_db
    permission = Permission(code="employees.leave.approve")
    role = Role(name="HR Approver", organization_id=f.org.id)
    f.session.add_all([permission, role]); f.session.flush()
    f.session.execute(role_permissions.insert().values(role_id=role.id, permission_id=permission.id))
    f.session.execute(user_roles.insert().values(role_id=role.id, user_id=f.manager.id))
    leave = LeaveRequest(organization_id=f.org.id, employee_id=f.employee.id,
        start_date=date.today(), end_date=date.today() + timedelta(days=2), status="PENDING")
    f.session.add(leave); f.session.commit()
    await notify_leave(f.db, leave)
    recipients = set(f.session.scalars(select(Notification.recipient_id)).all())
    assert f.manager.id in recipients and f.outsider.id not in recipients
    leave.status = "APPROVED"
    await notify_leave(f.db, leave)
    assert f.worker.id in set(f.session.scalars(select(Notification.recipient_id)).all())
