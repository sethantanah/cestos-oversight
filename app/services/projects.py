import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    Asset,
    AssetAssignment,
    Client,
    Employee,
    EmployeeAssignment,
    Location,
    Project,
    User,
)
from app.models.asset import AssetStatus
from app.models.employee import AssignmentStatus
from app.models.project import ProjectStatus
from app.repositories.base import organization_query
from app.schemas.asset import AssetAssignmentRead, AssetRead
from app.schemas.client import ClientRead
from app.schemas.common import Page
from app.schemas.employee import EmployeeAssignmentRead, EmployeeRead
from app.schemas.location import LocationRead
from app.schemas.project import (
    ProjectCreate,
    ProjectOverview,
    ProjectRead,
    ProjectUpdate,
)
from app.services.audit import RequestMetadata, record_audit, request_metadata
from app.services.counters import next_business_number


class ProjectService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def _scope(self) -> Select[tuple[Project]]:
        return organization_query(Project, self.actor.organization_id)

    async def _get_or_404(self, project_id: uuid.UUID) -> Project:
        project = (
            await self.session.scalars(self._scope().where(Project.id == project_id))
        ).one_or_none()
        if project is None:
            raise NotFoundError("Project not found")
        return project

    async def get(self, project_id: uuid.UUID) -> ProjectRead:
        return ProjectRead.model_validate(await self._get_or_404(project_id))

    async def list(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        client_id: uuid.UUID | None = None,
        status: ProjectStatus | None = None,
        project_manager_id: uuid.UUID | None = None,
        start_date_from: date | None = None,
        start_date_to: date | None = None,
    ) -> Page[ProjectRead]:
        query = self._scope()
        if search:
            like = f"%{search}%"
            query = query.where(
                or_(
                    Project.project_number.ilike(like),
                    Project.name.ilike(like),
                    Project.contract_number.ilike(like),
                )
            )
        if client_id is not None:
            query = query.where(Project.client_id == client_id)
        if status is not None:
            query = query.where(Project.status == status)
        if project_manager_id is not None:
            query = query.where(Project.project_manager_id == project_manager_id)
        if start_date_from is not None:
            query = query.where(Project.start_date >= start_date_from)
        if start_date_to is not None:
            query = query.where(Project.start_date <= start_date_to)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await self.session.scalars(
                query.order_by(Project.created_at, Project.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [ProjectRead.model_validate(row) for row in rows]
        return Page(
            items=items,
            total=total or 0,
            page=page,
            page_size=page_size,
            pages=math.ceil((total or 0) / page_size) if page_size else 0,
        )

    async def create(self, body: ProjectCreate, request: Request | None = None) -> ProjectRead:
        try:
            client = (
                await self.session.scalars(
                    select(Client).where(
                        Client.id == body.client_id,
                        Client.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if client is None:
                raise NotFoundError("Client not found")
            if body.project_manager_id is not None:
                manager = (
                    await self.session.scalars(
                        select(Employee).where(
                            Employee.id == body.project_manager_id,
                            Employee.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if manager is None:
                    raise NotFoundError("Project manager not found")
            if (
                body.start_date
                and body.expected_end_date
                and body.expected_end_date < body.start_date
            ):
                raise ValidationError("Expected end date cannot precede start date")
            number = await next_business_number(self.session, self.actor.organization_id, "project")
            project = Project(
                organization_id=self.actor.organization_id,
                project_number=number,
                client_id=body.client_id,
                name=body.name,
                description=body.description,
                project_type=body.project_type,
                drilling_type=body.drilling_type,
                contract_number=body.contract_number,
                project_manager_id=body.project_manager_id,
                start_date=body.start_date,
                expected_end_date=body.expected_end_date,
                actual_end_date=body.actual_end_date,
                status=body.status,
                contract_value=body.contract_value,
                target_metres=body.target_metres,
                default_currency=body.default_currency,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(project)
            await self.session.flush()
            meta: RequestMetadata = (
                request_metadata(request)
                if request is not None
                else {"ip_address": None, "user_agent": None}
            )
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="project.created",
                entity_type="project",
                entity_id=project.id,
                new_values={"project_number": number, "name": body.name},
                **meta,
            )
            await self.session.commit()
            return ProjectRead.model_validate(project)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, project_id: uuid.UUID, body: ProjectUpdate, request: Request | None = None
    ) -> ProjectRead:
        try:
            project = await self._get_or_404(project_id)
            data = body.model_dump(exclude_unset=True)
            if data.get("client_id") is not None:
                client = (
                    await self.session.scalars(
                        select(Client).where(
                            Client.id == data["client_id"],
                            Client.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if client is None:
                    raise NotFoundError("Client not found")
            if data.get("project_manager_id") is not None:
                manager = (
                    await self.session.scalars(
                        select(Employee).where(
                            Employee.id == data["project_manager_id"],
                            Employee.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if manager is None:
                    raise NotFoundError("Project manager not found")
            start = data.get("start_date", project.start_date)
            expected = data.get("expected_end_date", project.expected_end_date)
            if start and expected and expected < start:
                raise ValidationError("Expected end date cannot precede start date")
            for key, value in data.items():
                setattr(project, key, value)
            project.updated_by_id = self.actor.id
            project.updated_at = datetime.now(UTC)
            await self.session.flush()
            meta: RequestMetadata = (
                request_metadata(request)
                if request is not None
                else {"ip_address": None, "user_agent": None}
            )
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="project.updated",
                entity_type="project",
                entity_id=project.id,
                new_values={"name": project.name, "status": str(project.status)},
                **meta,
            )
            await self.session.commit()
            return ProjectRead.model_validate(project)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def project_employees(self, project_id: uuid.UUID) -> Sequence[EmployeeRead]:
        await self._get_or_404(project_id)
        assignment_rows = (
            await self.session.scalars(
                organization_query(EmployeeAssignment, self.actor.organization_id).where(
                    EmployeeAssignment.project_id == project_id,
                    EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        ).all()
        employee_ids = [a.employee_id for a in assignment_rows]
        if not employee_ids:
            return []
        rows = (
            await self.session.scalars(
                organization_query(Employee, self.actor.organization_id).where(
                    Employee.id.in_(employee_ids)
                )
            )
        ).all()
        return [EmployeeRead.model_validate(row) for row in rows]

    async def project_assets(self, project_id: uuid.UUID) -> Sequence[AssetRead]:
        await self._get_or_404(project_id)
        assignment_rows = (
            await self.session.scalars(
                organization_query(AssetAssignment, self.actor.organization_id).where(
                    AssetAssignment.project_id == project_id,
                    AssetAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        ).all()
        asset_ids = [a.asset_id for a in assignment_rows]
        if not asset_ids:
            return []
        rows = (
            await self.session.scalars(
                organization_query(Asset, self.actor.organization_id).where(Asset.id.in_(asset_ids))
            )
        ).all()
        from app.services.equipment import EquipmentService

        return [EquipmentService(self.session, self.actor).read_asset(row) for row in rows]

    async def project_sites(self, project_id: uuid.UUID) -> Sequence[LocationRead]:
        await self._get_or_404(project_id)
        rows = (
            await self.session.scalars(
                organization_query(Location, self.actor.organization_id).where(
                    Location.project_id == project_id
                )
            )
        ).all()
        return [LocationRead.model_validate(row) for row in rows]

    async def overview(self, project_id: uuid.UUID) -> ProjectOverview:
        project = await self._get_or_404(project_id)
        client = (
            await self.session.scalars(
                select(Client).where(
                    Client.id == project.client_id,
                    Client.organization_id == self.actor.organization_id,
                )
            )
        ).one_or_none()
        manager = None
        if project.project_manager_id is not None:
            manager_row = (
                await self.session.scalars(
                    select(Employee).where(
                        Employee.id == project.project_manager_id,
                        Employee.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if manager_row is not None:
                manager = EmployeeRead.model_validate(manager_row)
        sites = await self.project_sites(project_id)
        employees = await self.project_employees(project_id)
        assets = await self.project_assets(project_id)
        emp_assignments = (
            await self.session.scalars(
                organization_query(EmployeeAssignment, self.actor.organization_id)
                .where(EmployeeAssignment.project_id == project_id)
                .order_by(EmployeeAssignment.start_date.desc())
                .limit(20)
            )
        ).all()
        asset_assignments = (
            await self.session.scalars(
                organization_query(AssetAssignment, self.actor.organization_id)
                .where(AssetAssignment.project_id == project_id)
                .order_by(AssetAssignment.assigned_at.desc())
                .limit(20)
            )
        ).all()
        _ = AssetStatus  # keep import used for future status breakdowns
        return ProjectOverview(
            project=ProjectRead.model_validate(project),
            client=ClientRead.model_validate(client) if client else None,
            project_manager=manager,
            sites=sites,
            employee_count=len(employees),
            asset_count=len(assets),
            current_employees=employees,
            current_assets=assets,
            recent_employee_assignments=[
                EmployeeAssignmentRead.model_validate(a) for a in emp_assignments
            ],
            recent_asset_assignments=[
                AssetAssignmentRead.model_validate(a) for a in asset_assignments
            ],
        )
