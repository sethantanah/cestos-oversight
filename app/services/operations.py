from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Asset,
    AssetAssignment,
    Employee,
    EmployeeAssignment,
    Project,
    User,
)
from app.models.asset import AssetStatus
from app.models.employee import AssignmentStatus, EmploymentStatus
from app.models.project import ProjectStatus
from app.schemas.operations import (
    AssetSummary,
    EmployeeSummary,
    OperationsSummary,
    ProjectSummary,
)


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

        total_projects = (
            await self.session.scalar(
                select(func.count()).select_from(Project).where(Project.organization_id == org)
            )
        ) or 0
        active_projects = (
            await self.session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.organization_id == org, Project.status == ProjectStatus.ACTIVE)
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
                .where(Asset.organization_id == org, Asset.status == AssetStatus.OPERATING)
            )
        ) or 0
        available_assets = (
            await self.session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(Asset.organization_id == org, Asset.status == AssetStatus.AVAILABLE)
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
                .where(Asset.organization_id == org, Asset.status == AssetStatus.BREAKDOWN)
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
                unassigned=max(total_employees - assigned_count, 0),
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
        )
