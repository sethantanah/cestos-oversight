import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models import Asset, AssetAssignment, Employee, EmployeeAssignment, Location, Project
from app.services.activity import present_activity


async def test_legacy_activity_resolves_subjects_and_changes_without_rewriting_history():
    org = uuid.uuid4()
    employee, supervisor, project, assignment, asset, equipment, site = [
        uuid.uuid4() for _ in range(7)
    ]
    models = {
        EmployeeAssignment: [
            SimpleNamespace(id=assignment, employee_id=employee, project_id=project)
        ],
        AssetAssignment: [SimpleNamespace(id=equipment, asset_id=asset, project_id=project)],
        Employee: [
            SimpleNamespace(id=employee, first_name="Ada", last_name="Lovelace"),
            SimpleNamespace(id=supervisor, first_name="Grace", last_name="Hopper"),
        ],
        Project: [SimpleNamespace(id=project, name="North Mine")],
        Asset: [SimpleNamespace(id=asset, name="Drill Rig 7")],
        Location: [SimpleNamespace(id=site, name="North Site", project_id=project)],
    }

    async def scalars(statement):
        # Every lookup must remain scoped to the actor's organization.
        assert org in statement.compile().params.values()
        return SimpleNamespace(all=lambda: models[statement.column_descriptions[0]["entity"]])

    session = SimpleNamespace(scalars=AsyncMock(side_effect=scalars))

    def event(action, entity_type, entity_id, details, previous=None):
        return (
            SimpleNamespace(
                id=uuid.uuid4(),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                new_values=details,
                old_values=previous,
                actor_user_id=uuid.uuid4(),
                created_at=datetime.now(UTC),
            ),
            "Admin",
            "Superadmin",
        )

    legacy = {"assignment_number": "ASN-000006"}
    results = await present_activity(
        session,
        org,
        [
            event("employee.assigned", "employee_assignment", assignment, legacy),
            event(
                "employee.assignment_updated",
                "employee_assignment",
                assignment,
                {"supervisor_id": None},
                {"supervisor_id": str(supervisor)},
            ),
            event(
                "project.updated",
                "project",
                project,
                {"project_manager_id": str(supervisor)},
                {"project_manager_id": None},
            ),
            event("asset.assigned", "asset_assignments", equipment, {"asset_id": str(asset)}),
            event("location.created", "location", site, {"name": "North Site"}),
            event(
                "project.report_created",
                "project",
                project,
                {"title": "Morning Drilling", "site_name": "North Site", "metres": 100},
            ),
            event(
                "project.record_created",
                "project_record",
                uuid.uuid4(),
                {"project_id": str(project), "record_type": "NOTE", "title": "Shift handover"},
            ),
        ],
    )
    assert results[0]["title"] == "Employee Assigned"
    assert results[0]["summary"] == "Ada Lovelace added to North Mine"
    assert results[0]["author_name"] == "Admin Superadmin"
    assert legacy == {"assignment_number": "ASN-000006"}
    assert results[1]["previous"]["supervisor_id"] == "Grace Hopper"
    assert results[1]["details"]["supervisor_id"] is None
    assert results[2]["details"]["project_manager_id"] == "Grace Hopper"
    assert results[3]["summary"] == "Drill Rig 7 assigned to North Mine"
    assert results[4]["title"] == "Site Created"
    assert "North Site" in results[4]["summary"]
    assert results[5]["summary"] == "Morning Drilling submitted at North Site"
    assert results[6]["title"] == "Note Created"
    assert "Shift handover" in results[6]["summary"]


async def test_unavailable_subject_does_not_put_uuid_in_summary():
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    log = SimpleNamespace(
        id=uuid.uuid4(),
        action="employee.assigned",
        entity_type="employee_assignment",
        entity_id=uuid.uuid4(),
        new_values={"employee_id": str(uuid.uuid4())},
        old_values=None,
        actor_user_id=None,
        created_at=datetime.now(UTC),
    )
    result = (await present_activity(session, uuid.uuid4(), [(log, None, None)]))[0]
    assert result["summary"] == "An employee"
    assert result["author_name"] == "System"
