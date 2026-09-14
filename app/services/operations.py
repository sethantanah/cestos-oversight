from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import scoped_roles
from app.models import (
    Asset,
    AssetAssignment,
    AuditLog,
    Employee,
    EmployeeAssignment,
    Project,
    User,
)
from app.models.asset import AssetStatus
from app.models.employee import AssignmentStatus, AvailabilityStatus, EmploymentStatus
from app.models.project import ProjectStatus
from app.schemas.operations import (
    AssetSummary,
    EmployeeSummary,
    OperationsSummary,
    ProjectSummary,
)
from app.services.activity import present_activity
from app.services.employees import availability_map


class OperationsService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def summary(self) -> OperationsSummary:
        org = self.actor.organization_id

        total_employees = (
            await self.session.scalar(
                select(func.count()).select_from(Employee).where(Employee.organization_id == org)
            )
        ) or 0
        active_employees = (
            await self.session.scalar(
                select(func.count())
                .select_from(Employee)
                .where(
                    Employee.organization_id == org,
                    Employee.is_active == True,  # noqa: E712
                    Employee.employment_status == EmploymentStatus.ACTIVE,
                )
            )
        ) or 0
        assigned_employee_ids = (
            await self.session.scalars(
                select(EmployeeAssignment.employee_id).where(
                    EmployeeAssignment.organization_id == org,
                    EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        ).all()
        assigned_count = len(set(assigned_employee_ids))
        available_employees_count = max(total_employees - assigned_count, 0)
        employees = (
            await self.session.scalars(select(Employee).where(Employee.organization_id == org))
        ).all()
        availability = await availability_map(self.session, org, employees)
        deployable_employees = sum(
            state == AvailabilityStatus.AVAILABLE for state in availability.values()
        )

        total_projects = (
            await self.session.scalar(
                select(func.count()).select_from(Project).where(Project.organization_id == org)
            )
        ) or 0
        active_projects = (
            await self.session.scalar(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.organization_id == org,
                    Project.status == ProjectStatus.ACTIVE,
                    Project.is_active.is_(True),
                    Project.archived_at.is_(None),
                )
            )
        ) or 0
        planning_projects = (
            await self.session.scalar(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.organization_id == org,
                    Project.status.in_([ProjectStatus.PLANNING, ProjectStatus.MOBILIZING]),
                )
            )
        ) or 0
        paused_projects = (
            await self.session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.organization_id == org, Project.status == ProjectStatus.PAUSED)
            )
        ) or 0

        total_assets = (
            await self.session.scalar(
                select(func.count()).select_from(Asset).where(Asset.organization_id == org)
            )
        ) or 0
        operating_assets = (
            await self.session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(
                    Asset.organization_id == org,
                    Asset.status == AssetStatus.OPERATING,
                    Asset.is_active.is_(True),
                    Asset.archived_at.is_(None),
                )
            )
        ) or 0
        available_assets = (
            await self.session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(
                    Asset.organization_id == org,
                    Asset.status == AssetStatus.AVAILABLE,
                    Asset.is_active.is_(True),
                    Asset.archived_at.is_(None),
                    ~select(AssetAssignment.id)
                    .where(
                        AssetAssignment.organization_id == org,
                        AssetAssignment.asset_id == Asset.id,
                        AssetAssignment.status == AssignmentStatus.ACTIVE,
                    )
                    .exists(),
                )
            )
        ) or 0
        maintenance_assets = (
            await self.session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(
                    Asset.organization_id == org,
                    Asset.status == AssetStatus.UNDER_MAINTENANCE,
                )
            )
        ) or 0
        breakdown_assets = (
            await self.session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(
                    Asset.organization_id == org,
                    Asset.status == AssetStatus.BREAKDOWN,
                    Asset.is_active.is_(True),
                    Asset.archived_at.is_(None),
                )
            )
        ) or 0
        assigned_asset_ids = (
            await self.session.scalars(
                select(AssetAssignment.asset_id).where(
                    AssetAssignment.organization_id == org,
                    AssetAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        ).all()

        return OperationsSummary(
            employees=EmployeeSummary(
                total=total_employees,
                active=active_employees,
                assigned=assigned_count,
                unassigned=available_employees_count,
            ),
            projects=ProjectSummary(
                total=total_projects,
                active=active_projects,
                planning=planning_projects,
                paused=paused_projects,
            ),
            assets=AssetSummary(
                total=total_assets,
                operating=operating_assets,
                available=available_assets,
                maintenance=maintenance_assets,
                breakdown=breakdown_assets,
                unassigned=max(total_assets - len(set(assigned_asset_ids)), 0),
            ),
            active_projects=active_projects,
            active_employees=active_employees,
            operating_assets=operating_assets,
            available_employees=deployable_employees,
            available_assets=available_assets,
            breakdowns=breakdown_assets,
        )

    async def activity(self, page: int = 1, page_size: int = 20) -> dict:
        org = self.actor.organization_id
        permissions = {p.code for role in scoped_roles(self.actor) for p in role.permissions}

        def can(code: str) -> bool:
            return self.actor.is_superuser or code in permissions

        visible = [AuditLog.action.like("project.%")]
        if can("locations.read"):
            visible.append(AuditLog.action.like("location.%"))
        if can("employees.read_basic"):
            visible.append(
                AuditLog.action.in_(
                    [
                        "employee.created",
                        "employee.updated",
                        "employee.archived",
                        "employee.restored",
                        "employee.assigned",
                        "employee.transferred",
                        "employee.assignment_updated",
                        "employee.assignment_completed",
                        "employee.assignment_cancelled",
                    ]
                )
            )
        if can("assets.read"):
            visible.append(AuditLog.action.like("asset.%"))
        if can("inventory.read") or can("inventory.admin"):
            visible.append(AuditLog.action.like("inventory.%"))
        activity_scope = and_(AuditLog.organization_id == org, or_(*visible))
        total = (
            await self.session.scalar(select(func.count(AuditLog.id)).where(activity_scope))
        ) or 0

        stmt = (
            select(AuditLog, User.first_name, User.last_name)
            .outerjoin(User, and_(User.id == AuditLog.actor_user_id, User.organization_id == org))
            .where(activity_scope)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        results = (await self.session.execute(stmt)).all()
        items = await present_activity(self.session, org, results)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
