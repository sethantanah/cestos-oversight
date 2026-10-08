"""Cross-project reads use the real query against an isolated SQLite database."""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.employees import _list_employee_timesheets
from app.core.exceptions import ForbiddenError
from app.models import Employee, EmployeeAssignment, Project
from app.models.timesheet import EmployeeTimesheet, EmployeeTimesheetDay


@pytest.mark.asyncio
async def test_field_admin_reads_all_assigned_projects_and_latest_accessible_month():
    engine = create_engine("sqlite://")
    for model in (Employee, EmployeeAssignment, Project, EmployeeTimesheet, EmployeeTimesheetDay):
        model.__table__.create(engine)
    org, user = uuid.uuid4(), uuid.uuid4()
    actor = SimpleNamespace(id=user, organization_id=org, portal_type="FIELD_ADMIN")
    with Session(engine) as session:
        manager = Employee(organization_id=org, employee_number="MANAGER", first_name="Manager", last_name="User", user_id=user)
        member = Employee(organization_id=org, employee_number="MEMBER", first_name="Member", last_name="User")
        session.add_all([manager, member]); session.flush()
        projects = []
        for index in range(3):
            project = Project(organization_id=org, project_number=f"P{index}", name=f"Project {index}", client_id=uuid.uuid4(), project_manager_id=manager.id if index < 2 else None)
            session.add(project); projects.append(project)
        session.flush()
        session.add(EmployeeAssignment(organization_id=org, employee_id=member.id, project_id=projects[0].id, assignment_number="A1", start_date=date.today(), status="ACTIVE"))
        for name, project, month, organization, employee in [
            ("A", projects[0], date(2026, 9, 1), org, None),
            ("B", projects[1], date(2026, 9, 1), org, None),
            ("Hidden newer", projects[2], date(2026, 10, 1), org, None),
            ("Other tenant", projects[0], date(2026, 9, 1), uuid.uuid4(), None),
            ("Assigned member", None, date(2026, 9, 1), org, member),
        ]:
            session.add(EmployeeTimesheet(organization_id=organization, employee_name=name, employee_id=employee.id if employee else None, project_id=project.id if project else None, scope_project_id=project.id if project else None, period_start=month))
        session.commit()
        async def scalar(query): return session.scalar(query)
        async def scalars(query): return session.scalars(query)
        database = SimpleNamespace(scalar=scalar, scalars=scalars)
        result = await _list_employee_timesheets(None, None, actor, database)
        assert result["period"] == "2026-09"
        assert {row["employee_name"] for row in result["items"]} == {"A", "B", "Member User"}
        selected = await _list_employee_timesheets("2026-09", projects[1].id, actor, database)
        assert [row["employee_name"] for row in selected["items"]] == ["B"]
        assert selected["items"][0]["scope_project_id"] == str(projects[1].id)
        with pytest.raises(ForbiddenError):
            await _list_employee_timesheets(None, projects[2].id, actor, database)
        no_projects = SimpleNamespace(id=uuid.uuid4(), organization_id=org, portal_type="FIELD_ADMIN")
        assert (await _list_employee_timesheets("2026-09", None, no_projects, database))["items"] == []
        hr = SimpleNamespace(id=user, organization_id=org, portal_type="HR")
        all_org = await _list_employee_timesheets(None, None, hr, database)
        assert all_org["period"] == "2026-10"
        assert [row["employee_name"] for row in all_org["items"]] == ["Hidden newer"]
    engine.dispose()
