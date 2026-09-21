"""Field project boundaries, completion evidence and unapproved shift edits."""

import io
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from app.api.v1.endpoints.work_completion import (
    asset_completion,
    complete_work_order,
    field_completion,
    field_completion_file,
)
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.storage import LocalStorage
from app.models import AssetAssignment, EmployeeAssignment, Project, Role
from app.models.asset import AssetMeterReading
from app.models.drilling import (
    DrillHole,
    DrillingShiftCrew,
    DrillingShiftInterval,
    DrillingShiftReport,
    DrillingShiftTimeSegment,
)
from app.models.operational_logs import AssetFuelLog, AssetLogFile
from app.services import drilling, field_notifications
from app.services.field_equipment import equipment_history, field_equipment
from app.services.field_shifts import FieldShiftEdit, edit_shift
from app.services.field_work import edit_work
from app.tests.test_field_work import edit_payload
from app.tests.test_field_work import field_db as field_fixture
from app.tests.test_field_work import work_db as work_fixture

field_db = field_fixture
work_db = work_fixture


@pytest.fixture
def records_db(request, monkeypatch):
    f = request.getfixturevalue("work_db")
    for model in (
        AssetFuelLog,
        AssetLogFile,
        AssetMeterReading,
        DrillHole,
        DrillingShiftReport,
        DrillingShiftInterval,
        DrillingShiftTimeSegment,
        DrillingShiftCrew,
    ):
        model.__table__.create(f.session.get_bind())
    f.db.rollback = AsyncMock(side_effect=f.session.rollback)
    monkeypatch.setattr(field_notifications, "notify_work_order", AsyncMock())
    f.project = Project(
        organization_id=f.org.id, project_number="P1", name="Same name", client_id=uuid.uuid4()
    )
    f.other_project = Project(
        organization_id=f.org.id, project_number="P2", name="Same name", client_id=uuid.uuid4()
    )
    f.session.add_all([f.project, f.other_project])
    f.session.flush()
    f.assignment = EmployeeAssignment(
        organization_id=f.org.id,
        assignment_number="EA1",
        employee_id=f.employee.id,
        supervisor_id=f.boss.id,
        project_id=f.project.id,
        status="ACTIVE",
        start_date=date.today() - timedelta(days=2),
    )
    f.asset_assignment = AssetAssignment(
        organization_id=f.org.id,
        assignment_number="AA1",
        asset_id=f.job.asset_id,
        project_id=f.project.id,
        status="ACTIVE",
        assigned_at=datetime.now(UTC) - timedelta(days=1),
    )
    f.job.project_id = f.project.id
    f.session.add_all([f.assignment, f.asset_assignment])
    f.session.commit()
    return f


async def test_equipment_requires_current_project_assignment_for_every_role(records_db):
    f = records_db
    for actor in (f.worker, f.supervisor):
        rows = await field_equipment(f.db, actor, f.project.id)
        assert [row["id"] for row in rows] == [f.job.asset_id]
        with pytest.raises(NotFoundError):
            await field_equipment(f.db, actor, f.other_project.id)
        history = await equipment_history(f.db, actor, f.project.id, f.job.asset_id, "maintenance")
        assert history["total"] == 2
        assert history["items"][0]["title"] == f.job.title
        with pytest.raises(NotFoundError):
            await equipment_history(f.db, actor, f.project.id, uuid.uuid4(), "fuel")
    with pytest.raises(NotFoundError):
        await field_equipment(f.db, f.outsider, f.project.id)
    f.assignment.end_date = date.today() - timedelta(days=1)
    f.session.commit()
    with pytest.raises(NotFoundError):
        await field_equipment(f.db, f.worker, f.project.id)


async def test_returned_equipment_and_financial_data_are_not_exposed(records_db):
    f = records_db
    f.session.add(
        AssetFuelLog(
            organization_id=f.org.id,
            asset_id=f.job.asset_id,
            recorded_at=datetime.now(UTC),
            fuel_type="DIESEL",
            quantity_litres=12,
            unit_cost=5,
            currency="USD",
        )
    )
    f.session.commit()
    result = await equipment_history(f.db, f.worker, f.project.id, f.job.asset_id, "fuel")
    assert result["items"][0]["quantity_litres"] == 12
    assert "unit_cost" not in result["items"][0]
    f.asset_assignment.returned_at = datetime.now(UTC) - timedelta(seconds=1)
    f.session.commit()
    assert await field_equipment(f.db, f.worker, f.project.id) == []


async def test_ordinary_assignee_cannot_edit_work_details(records_db):
    f = records_db
    with pytest.raises(ForbiddenError):
        await edit_work(f.db, f.worker, f.job.id, edit_payload(f.job))


async def test_completion_file_and_notes_survive_reload_and_both_portals(records_db, tmp_path):
    f = records_db
    f.job.checklist = []
    f.session.commit()
    storage = LocalStorage(tmp_path, 1024)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    result = await complete_work_order(
        f.job.id,
        request,
        "Replaced hydraulic seal",
        UploadFile(filename="inspection.pdf", file=io.BytesIO(b"test evidence")),
        f.worker,
        f.db,
    )
    assert result["status"] == "COMPLETED"
    f.session.expire(f.job)
    field = await field_completion(f.job.id, f.worker, f.db)
    main = await asset_completion(f.job.asset_id, "MAINTENANCE", f.job.id, f.supervisor, f.db)
    assert field["completion_notes"] == main["completion_notes"] == "Replaced hydraulic seal"
    assert field["files"][0]["file_name"] == main["files"][0]["file_name"] == "inspection.pdf"
    response = await field_completion_file(
        f.job.id, field["files"][0]["id"], request, f.worker, f.db
    )
    assert response.path.read_bytes() == b"test evidence"
    with pytest.raises(NotFoundError):
        await field_completion_file(f.job.id, field["files"][0]["id"], request, f.outsider, f.db)


async def test_failed_file_upload_does_not_complete_work(records_db, tmp_path):
    f = records_db
    f.job.checklist = []
    f.session.commit()
    storage = LocalStorage(tmp_path, 3)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    with pytest.raises(ValidationError):
        await complete_work_order(
            f.job.id,
            request,
            "Done",
            UploadFile(filename="large.pdf", file=io.BytesIO(b"too large")),
            f.worker,
            f.db,
        )
    assert f.job.status == "OPEN" and f.job.completed_at is None
    assert not list(tmp_path.rglob("*.pdf"))


def test_role_check_uses_real_role_name_without_nonexistent_code():
    assert drilling.has_shift_reporting_role([Role(name="Supervisor")])
    assert not drilling.has_shift_reporting_role([Role(name="Employee")])


@pytest.mark.parametrize("status", ["DRAFT", "SUBMITTED", "RETURNED", "APPROVED"])
async def test_shift_edits_persist_and_approved_shifts_are_locked(records_db, monkeypatch, status):
    f = records_db
    monkeypatch.setattr(drilling, "enrich_shift_reports", AsyncMock())
    shift = DrillingShiftReport(
        organization_id=f.org.id,
        report_number="SHIFT1",
        project_id=f.project.id,
        rig_id=f.job.asset_id,
        date=date.today(),
        shift_type="DAY",
        status=status,
        notes="Original",
        crew_members=[],
        intervals=[],
        time_segments=[],
    )
    f.session.add(shift)
    f.session.commit()
    body = FieldShiftEdit(notes="Corrected notes", shift_type="NIGHT")
    if status == "APPROVED":
        with pytest.raises(ConflictError):
            await edit_shift(f.db, f.supervisor, shift.id, body)
        assert shift.notes == "Original"
    else:
        result = await edit_shift(f.db, f.supervisor, shift.id, body)
        assert result.notes == "Corrected notes" and result.shift_type == "NIGHT"
        assert result.status == status
    with pytest.raises(ForbiddenError):
        await edit_shift(f.db, f.worker, shift.id, body)


def test_shift_edit_rejects_status_and_approval_bypass():
    from pydantic import ValidationError as SchemaError

    for extra in (
        {"status": "DRAFT"},
        {"correction_reason": "Override"},
        {"project_id": str(uuid.uuid4())},
        {"approved_at": None},
    ):
        with pytest.raises(SchemaError):
            FieldShiftEdit(**extra)


async def test_detailed_completion_evidence_and_failed_commit_cleanup(records_db, tmp_path):
    from app.models.maintenance_hse import MaintenanceWorkOrder

    f = records_db
    order = MaintenanceWorkOrder(
        organization_id=f.org.id,
        asset_id=f.job.asset_id,
        wo_number="WO-EVIDENCE",
        title="Repair",
        assigned_technician_id=f.employee.id,
    )
    f.session.add(order)
    f.session.commit()
    storage = LocalStorage(tmp_path, 1024)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=storage)))
    await complete_work_order(
        order.id,
        request,
        "Seal replaced",
        UploadFile(filename="proof.pdf", file=io.BytesIO(b"proof")),
        f.worker,
        f.db,
    )
    result = await asset_completion(order.asset_id, "WORK_ORDER", order.id, f.supervisor, f.db)
    assert "Seal replaced" in result["completion_notes"]
    assert result["files"][0]["file_name"] == "proof.pdf"
    f.job.checklist = []
    f.session.commit()
    f.db.commit = AsyncMock(side_effect=RuntimeError("Commit failed"))
    with pytest.raises(RuntimeError, match="Commit failed"):
        await complete_work_order(
            f.job.id,
            request,
            "Done",
            UploadFile(filename="failed.pdf", file=io.BytesIO(b"failed")),
            f.worker,
            f.db,
        )
    assert f.job.status == "OPEN"
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


async def test_shift_production_edit_preserves_crew_and_project_boundary(records_db, monkeypatch):
    f = records_db
    monkeypatch.setattr(drilling, "enrich_shift_reports", AsyncMock())
    hole = DrillHole(organization_id=f.org.id, project_id=f.project.id, hole_number="H1")
    foreign = DrillHole(organization_id=f.org.id, project_id=f.other_project.id, hole_number="H2")
    shift = DrillingShiftReport(
        organization_id=f.org.id,
        report_number="SHIFT2",
        project_id=f.project.id,
        rig_id=f.job.asset_id,
        date=date.today(),
        shift_type="DAY",
        status="SUBMITTED",
        intervals=[],
        time_segments=[],
        crew_members=[
            DrillingShiftCrew(
                organization_id=f.org.id,
                employee_id=f.employee.id,
                role_on_shift="Driller",
                hours_worked=12,
            )
        ],
    )
    f.session.add_all([hole, foreign, shift])
    f.session.commit()
    crew_id = shift.crew_members[0].id
    result = await edit_shift(
        f.db,
        f.supervisor,
        shift.id,
        FieldShiftEdit(
            intervals=[
                dict(drill_hole_id=hole.id, from_depth_m=10, to_depth_m=20, core_recovered_m=8)
            ],
            time_segments=[dict(category="PRODUCTIVE", reason_code="DRILLING", hours=6)],
        ),
    )
    assert result.total_metres == 10 and result.total_productive_hours == 6
    assert result.crew_members[0].id == crew_id
    with pytest.raises(ValidationError, match="drill holes"):
        await edit_shift(
            f.db,
            f.supervisor,
            shift.id,
            FieldShiftEdit(
                intervals=[dict(drill_hole_id=foreign.id, from_depth_m=0, to_depth_m=1)]
            ),
        )
