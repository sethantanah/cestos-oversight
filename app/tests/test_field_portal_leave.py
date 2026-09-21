"""Exercise the actual leave route and SQL scope against an isolated database."""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.field_portal import router
from app.core.dependencies import get_current_active_user
from app.core.exceptions import install_exception_handlers
from app.db.session import get_session
from app.models import Employee, EmployeeAssignment, Role
from app.models.employee import LeaveRequest


def test_app(actor, session=None):
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(router)

    async def current_user():
        return actor

    async def execute(query):
        assert session is not None, "Unauthorized users must not query leave data"
        return session.execute(query)

    async def database():
        return SimpleNamespace(execute=execute)

    app.dependency_overrides[get_current_active_user] = current_user
    app.dependency_overrides[get_session] = database
    return app


test_app.__test__ = False


@pytest.mark.parametrize("role_name,superuser", [
    ("Operator", False), ("Manager", False), ("Lead", False),
    ("Admin", True), ("Assistant Supervisor", False),
])
async def test_other_roles_cannot_read_team_leave(role_name, superuser):
    org = uuid.uuid4()
    actor = SimpleNamespace(
        id=uuid.uuid4(), organization_id=org, is_superuser=superuser,
        roles=[Role(name=role_name, organization_id=org, permissions=[])],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app(actor)), base_url="http://test",
    ) as client:
        response = await client.get("/field-portal/team-leave-requests")
    assert response.status_code == 403


async def test_foreign_organization_supervisor_role_is_not_a_grant():
    actor = SimpleNamespace(
        id=uuid.uuid4(), organization_id=uuid.uuid4(), is_superuser=False,
        roles=[Role(name="Supervisor", organization_id=uuid.uuid4(), permissions=[])],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app(actor)), base_url="http://test",
    ) as client:
        assert (await client.get("/field-portal/team-leave-requests")).status_code == 403


@pytest.mark.parametrize("superuser", [False, True])
async def test_supervisor_leave_is_scoped_to_team_and_selected_project(superuser):
    engine = create_engine("sqlite://")
    for model in (Employee, EmployeeAssignment, LeaveRequest):
        model.__table__.create(engine)
    org, actor_id, project_a, project_b = (uuid.uuid4() for _ in range(4))
    actor = SimpleNamespace(
        id=actor_id, organization_id=org, is_superuser=superuser,
        roles=[Role(name=" Supervisor ", organization_id=org, permissions=[])],
    )
    with Session(engine) as session:
        def employee(number, **values):
            row = Employee(
                organization_id=values.pop("organization_id", org), employee_number=number,
                first_name=number, last_name="Person", **values,
            )
            session.add(row)
            session.flush()
            return row

        supervisor = employee("SUP", user_id=actor_id)
        team_a = employee("TEAM-A", supervisor_id=supervisor.id)
        team_b = employee("TEAM-B", supervisor_id=supervisor.id)
        hidden = employee("HIDDEN")
        outsider = employee("OTHER-ORG", organization_id=uuid.uuid4())
        for member, project in [(team_a, project_a), (team_b, project_b)]:
            session.add(EmployeeAssignment(
                organization_id=org, employee_id=member.id, project_id=project,
                assignment_number=member.employee_number, start_date=date.today(), status="ACTIVE",
            ))
        for member in [team_a, team_b, hidden, outsider]:
            session.add(LeaveRequest(
                organization_id=member.organization_id, employee_id=member.id,
                leave_type="Annual", start_date=date.today(),
                end_date=date.today() + timedelta(days=2), reason="Family visit",
                status="PENDING", notes="Travel planned",
            ))
        session.commit()
        session.info["document_actor"] = actor
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=test_app(actor, session)), base_url="http://test",
        ) as client:
            response = await client.get("/field-portal/team-leave-requests")
            assert response.status_code == 200, response.text
            assert {row["employee_number"] for row in response.json()} == {"TEAM-A", "TEAM-B"}
            response = await client.get(
                "/field-portal/team-leave-requests", params={"project_id": str(project_b)},
            )
            assert response.status_code == 200, response.text
            [leave] = response.json()
            assert leave["employee_number"] == "TEAM-B"
            assert leave["days"] == 3
            assert leave["status"] == "PENDING"
            assert leave["reason"] == "Family visit"
            assert leave["notes"] == "Travel planned"
            assert "attachment_url" not in leave
            empty = await client.get(
                "/field-portal/team-leave-requests", params={"project_id": str(uuid.uuid4())},
            )
            assert empty.json() == []
            # Ended assignments no longer put employees in the selected project.
            for assignment in session.query(EmployeeAssignment).all():
                if assignment.project_id == project_b:
                    assignment.end_date = date.today() - timedelta(days=1)
            session.flush()
            ended = await client.get(
                "/field-portal/team-leave-requests", params={"project_id": str(project_b)},
            )
            assert ended.json() == []
    engine.dispose()
