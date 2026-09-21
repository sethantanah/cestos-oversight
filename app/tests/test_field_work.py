import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models import Asset, Role
from app.models.operational_logs import AssetMaintenanceJob
from app.models.role import user_roles
from app.services.field_work import FieldWorkUpdate, list_work, update_work
from app.tests.test_field_notifications import field_db as field_fixture

field_db = field_fixture


@pytest.fixture
def work_db(request):
    f = request.getfixturevalue("field_db")
    Asset.__table__.create(f.session.get_bind())
    asset = Asset(organization_id=f.org.id, name="Rig", asset_number="R1", category_id=uuid.uuid4())
    f.session.add(asset)
    f.session.flush()
    for user in [f.worker, f.supervisor, f.manager, f.outsider]:
        roles = f.session.scalars(
            select(Role)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user.id)
        ).all()
        set_committed_value(user, "roles", roles)
    f.job = AssetMaintenanceJob(
        organization_id=f.org.id,
        asset_id=asset.id,
        title="Assigned service",
        assigned_employee_id=f.employee.id,
        maintenance_type="SERVICE",
        priority="NORMAL",
        currency="USD",
        scheduled_date=date.today(),
        checklist=[{"id": "1", "task": "Check oil", "completed": False}],
    )
    f.other_job = AssetMaintenanceJob(
        organization_id=f.org.id,
        asset_id=asset.id,
        title="Other employee",
        assigned_employee_id=f.boss.id,
        maintenance_type="SERVICE",
        priority="NORMAL",
        currency="USD",
    )
    f.session.add_all([f.job, f.other_job])
    f.session.commit()
    return f


async def test_assigned_list_not_asset_wide_and_no_planning(work_db):
    f = work_db
    rows = await list_work(f.db, f.worker)
    assert [r["id"] for r in rows] == [f.job.id]
    with pytest.raises(ForbiddenError):
        await list_work(f.db, f.worker, planning=True)
    assert await list_work(f.db, f.worker, project_id=uuid.uuid4()) == []


async def test_foreign_or_unassigned_work_is_inaccessible(work_db):
    f = work_db
    for actor, job in [(f.worker, f.other_job), (f.outsider, f.job)]:
        with pytest.raises(NotFoundError):
            await update_work(f.db, actor, job.id, FieldWorkUpdate(note="Changed"))


async def test_checklist_notes_completion_and_supervisor_approval_persist(work_db, monkeypatch):
    from app.services import field_notifications

    monkeypatch.setattr(field_notifications, "notify_work_order", AsyncMock())
    f = work_db
    with pytest.raises(ConflictError):
        await update_work(f.db, f.worker, f.job.id, FieldWorkUpdate(status="COMPLETED"))
    await update_work(
        f.db, f.worker, f.job.id, FieldWorkUpdate(task_id="1", completed=True, note="Oil checked")
    )
    f.session.expire(f.job)
    assert f.job.checklist[0]["completed"] and "Oil checked" in f.job.field_notes
    result = await update_work(f.db, f.worker, f.job.id, FieldWorkUpdate(status="COMPLETED"))
    assert result["status"] == "COMPLETED" and result["approved_at"] is None
    with pytest.raises(ForbiddenError):
        await update_work(f.db, f.worker, f.job.id, FieldWorkUpdate(status="APPROVED"))
    result = await update_work(f.db, f.supervisor, f.job.id, FieldWorkUpdate(status="APPROVED"))
    assert result["status"] == "APPROVED"
    assert f.job.approved_by_id == f.supervisor.id
    with pytest.raises(ConflictError):
        await update_work(f.db, f.worker, f.job.id, FieldWorkUpdate(note="Edit approved work"))


async def test_managers_cannot_approve_or_replace_checklist(work_db):
    f = work_db
    with pytest.raises(NotFoundError):
        await update_work(f.db, f.manager, f.job.id, FieldWorkUpdate(status="APPROVED"))
    with pytest.raises(ConflictError):
        await update_work(f.db, f.worker, f.job.id, FieldWorkUpdate(task_id="fake", completed=True))
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FieldWorkUpdate(checklist=[])


async def test_detailed_register_assignments_are_included(work_db, monkeypatch):
    from app.models.maintenance_hse import MaintenanceWorkOrder
    from app.services import field_notifications

    monkeypatch.setattr(field_notifications, "notify_work_order", AsyncMock())
    f = work_db
    order = MaintenanceWorkOrder(
        organization_id=f.org.id,
        asset_id=f.job.asset_id,
        wo_number="WO-DETAIL",
        title="Detailed work",
        assigned_technician_id=f.employee.id,
    )
    f.session.add(order)
    f.session.commit()
    ids = {row["id"] for row in await list_work(f.db, f.worker)}
    assert ids == {f.job.id, order.id}
    result = await update_work(
        f.db, f.worker, order.id, FieldWorkUpdate(note="Finished", status="COMPLETED")
    )
    assert result["status"] == "COMPLETED"
    result = await update_work(f.db, f.supervisor, order.id, FieldWorkUpdate(status="APPROVED"))
    assert result["status"] == "APPROVED"


async def test_basic_employee_can_log_fuel_without_supervisor(work_db):
    from app.api.v1.endpoints.field_portal import require_field_employee

    f = work_db
    assert await require_field_employee(f.worker, f.db) is f.worker
    f.employee.is_active = False
    f.session.commit()
    with pytest.raises(ForbiddenError):
        await require_field_employee(f.worker, f.db)


def edit_payload(job, **changes):
    from app.services.field_work import FieldWorkEdit

    data = dict(
        title="Updated service",
        description="Revised scope",
        maintenance_type="PREVENTIVE",
        priority="HIGH",
        scheduled_date=date(2026, 10, 1),
        assigned_employee_id=getattr(job, "assigned_employee_id", None)
        or getattr(job, "assigned_technician_id", None),
    )
    data.update(changes)
    return FieldWorkEdit(**data)


@pytest.mark.parametrize("detailed", [False, True])
async def test_edit_open_work_persists_without_resetting_progress(work_db, monkeypatch, detailed):
    from app.models.maintenance_hse import MaintenanceWorkOrder
    from app.services import field_notifications
    from app.services.field_work import edit_work

    notify = AsyncMock()
    monkeypatch.setattr(field_notifications, "notify_work_order", notify)
    f = work_db
    job = f.job
    if detailed:
        job = MaintenanceWorkOrder(
            organization_id=f.org.id,
            asset_id=f.job.asset_id,
            wo_number="WO-EDIT",
            title="Detailed",
            assigned_technician_id=f.employee.id,
            checklist=[{"id": "1", "task": "Check oil", "completed": True}],
        )
        f.session.add(job)
    job.status = "IN_PROGRESS"
    job.field_notes = "Preserve this note"
    f.session.commit()
    checklist = job.checklist
    result = await edit_work(f.db, f.supervisor, job.id, edit_payload(job))
    f.session.expire(job)
    assert result["title"] == job.title == "Updated service"
    assert job.description == "Revised scope"
    assert job.scheduled_date == date(2026, 10, 1)
    assert job.status == "IN_PROGRESS"
    assert job.field_notes == "Preserve this note"
    assert job.checklist == checklist
    assert job.updated_by_id == f.supervisor.id
    notify.assert_awaited_once_with(f.db, job, "updated")


@pytest.mark.parametrize(
    "status,approved",
    [("COMPLETED", False), ("COMPLETED", True), ("OPEN", True), ("CANCELLED", False)],
)
async def test_edit_rejects_locked_work_even_for_supervisor(work_db, status, approved):
    from datetime import UTC, datetime

    from app.services.field_work import edit_work

    f = work_db
    f.job.status = status
    f.job.approved_at = datetime.now(UTC) if approved else None
    f.session.commit()
    for actor in (f.supervisor,):
        with pytest.raises(ConflictError):
            await edit_work(f.db, actor, f.job.id, edit_payload(f.job))
    assert f.job.title == "Assigned service"
    assert not (await list_work(f.db, f.worker))[0]["can_edit"]


async def test_edit_permissions_and_reassignment_are_team_scoped(work_db, monkeypatch):
    from app.services import field_notifications
    from app.services.field_work import edit_work

    monkeypatch.setattr(field_notifications, "notify_work_order", AsyncMock())
    f = work_db
    for actor in (f.manager, f.outsider):
        with pytest.raises(NotFoundError):
            await edit_work(f.db, actor, f.job.id, edit_payload(f.job))
    with pytest.raises(ForbiddenError):
        await edit_work(
            f.db, f.worker, f.job.id, edit_payload(f.job, assigned_employee_id=f.boss.id)
        )
    with pytest.raises(ForbiddenError):
        await edit_work(
            f.db, f.supervisor, f.job.id, edit_payload(f.job, assigned_employee_id=uuid.uuid4())
        )
    assert f.job.assigned_employee_id == f.employee.id
    await edit_work(
        f.db,
        f.supervisor,
        f.job.id,
        edit_payload(
            f.job, assigned_employee_id=f.boss.id, is_recurring=True, recurrence_interval_days=14
        ),
    )
    assert f.job.assigned_employee_id == f.boss.id
    assert f.job.is_recurring and f.job.recurrence_interval_days == 14
    assert await list_work(f.db, f.worker) == []


def test_edit_rejects_blank_title_and_progress_or_approval_overrides(work_db):
    from pydantic import ValidationError

    for changes in (
        {"title": "  "},
        {"status": "OPEN"},
        {"checklist": []},
        {"approved_at": None},
        {"is_recurring": True},
        {"recurrence_interval_days": 0},
    ):
        with pytest.raises(ValidationError):
            edit_payload(work_db.job, **changes)
