from __future__ import annotations

import math
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models import Permission, Role, User
from app.repositories.user import UserRepository
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.audit import record_audit, request_metadata
from app.services.supabase_auth import SupabaseAuthSyncService


class UserService:
    def __init__(self, session: AsyncSession, actor: User, settings: Settings | None = None):
        self.session = session
        self.actor = actor
        self.settings = settings
        self.repository = UserRepository(session, actor.organization_id)

    async def list(self, page: int, page_size: int) -> Page[UserRead]:
        users, total = await self.repository.list(page, page_size)
        return Page(
            items=[UserRead.model_validate(user) for user in users],
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size),
        )

    async def get(self, user_id: uuid.UUID) -> UserRead:
        user = await self.repository.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return UserRead.model_validate(user)

    async def create(self, body: UserCreate, request: Request) -> UserRead:
        # Authentication already opened the request transaction. This use case owns its commit.
        try:
            email_clean = str(body.email).lower().strip()
            user = User(
                organization_id=self.actor.organization_id,
                email=email_clean,
                password_hash=await run_in_threadpool(
                    hash_password, body.password.get_secret_value()
                ),
                first_name=body.first_name,
                last_name=body.last_name,
                is_field_portal_only=body.is_field_portal_only,
                setup_required=True,
            )
            self.session.add(user)
            await self.session.flush()

            # Associate with existing employee profile if emails match
            from app.models import Employee
            from app.models.hr import EmailDelivery
            from sqlalchemy import select, or_
            from datetime import UTC, datetime

            employee = await self.session.scalar(
                select(Employee).where(
                    Employee.organization_id == self.actor.organization_id,
                    or_(Employee.work_email == email_clean, Employee.personal_email == email_clean),
                ).with_for_update()
            )
            if employee:
                employee.user_id = user.id
                employee.work_email = email_clean

            # Enqueue password setup/reset email
            self.session.add(
                EmailDelivery(
                    organization_id=self.actor.organization_id,
                    recipient_id=user.id,
                    kind="SETUP",
                    message="Set up your Cestos account password",
                    next_attempt_at=datetime.now(UTC),
                )
            )

            settings = self.settings or request.app.state.settings
            supabase_user_id = SupabaseAuthSyncService(settings).sync_user(
                user,
                password=body.password.get_secret_value(),
            )
            if supabase_user_id:
                user.supabase_user_id = supabase_user_id

            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="CREATE",
                entity_type="user",
                entity_id=user.id,
                new_values={"email": user.email},
                **request_metadata(request),
            )
            await self.session.commit()
            loaded = await self.repository.get(user.id)
            return UserRead.model_validate(loaded or user)
        except Exception:
            await self.session.rollback()
            raise

    async def list_permissions(self) -> list[Permission]:
        from sqlalchemy import select
        from app.models import Permission

        system_perms = [
            ("projects.read", "Read basic project information"),
            ("projects.read_all", "Read all organization projects without assignment restrictions"),
            ("projects.read_assigned", "Read only projects assigned to the user or their team"),
            ("projects.financials.read", "View sensitive project financials and budget values"),
            ("projects.create", "Create new projects"),
            ("projects.update", "Update project details and settings"),
            ("projects.tasks.manage", "Assign tasks to self/others and manage project task logs"),
            ("employees.read_basic", "View workforce records"),
            ("employees.create", "Create new employee profiles"),
            ("employees.write", "Update employee profile details"),
            ("employees.contracts.read", "View employment contract documents"),
            ("employees.contracts.write", "Upload, update, or archive employment contract documents"),
            ("employees.salary.read", "View salary records"),
            ("employees.salary.write", "Create or close salary periods"),
            ("employees.salary.manage", "Record or end salary periods"),
            ("employees.alerts.manage", "Manage contract alert rules"),
            ("departments.manage", "Create, update, or delete departments"),
            ("positions.manage", "Create, update, or delete positions"),
            ("assets.read", "View equipment register"),
            ("assets.read_assigned", "View only equipment assigned to the user or their team"),
            ("assets.read_write", "Read and update equipment details and operational status"),
            ("assets.create", "Add new equipment"),
            ("assets.update", "Update equipment details"),
            ("assets.assignments.manage", "Assign equipment to projects or operators"),
            ("assets.logs.write", "Record maintenance, fuel, and meter logs"),
            ("assets.transfers.manage", "Perform equipment transfers across sites/stores"),
            ("assets.archive", "Retire or archive equipment"),
            ("inventory.read", "View inventory catalog, stock balances, and stores"),
            ("inventory.read_assigned", "View only assigned stores, stock, or project inventory"),
            ("inventory.requests.create", "Submit material requests"),
            ("inventory.requests.manage", "Approve or reject material requests"),
            ("inventory.write", "Post receipts, issues, transfers, and adjustments"),
            ("inventory.audits.manage", "Conduct stock counts and audits"),
            ("inventory.manage", "Full inventory administration and access configuration"),
            ("users.read", "View system users and security roles"),
            ("users.create", "Create and update user accounts and role assignments"),
            ("roles.manage", "Manage roles and edit permission matrix"),
            ("drilling.shifts.create", "Create daily shift production reports"),
            ("drilling.shifts.approve", "Approve daily shift production reports and trigger commercial revenue posting"),
            ("reports.approve", "Approve field reports, operational updates, and shift production summaries"),
            ("documents.download", "Download raw files and sensitive attachments"),
        ]

        existing = set((await self.session.scalars(select(Permission.code))).all())
        added = False
        for code, desc in system_perms:
            if code not in existing:
                self.session.add(Permission(code=code, description=desc))
                added = True
        if added:
            await self.session.commit()

        query = select(Permission).order_by(Permission.code)
        return list((await self.session.scalars(query)).all())

    async def list_roles(self) -> list[Role]:
        from sqlalchemy import or_, select
        from sqlalchemy.orm import selectinload
        from app.models import Role

        await self.list_permissions()

        query = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(
                or_(
                    Role.organization_id == self.actor.organization_id,
                    Role.is_system_role.is_(True),
                )
            )
            .order_by(Role.name)
        )
        return list((await self.session.scalars(query)).all())

    async def create_role(
        self, name: str, description: str | None, permission_codes: list[str]
    ) -> Role:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.core.exceptions import ConflictError
        from app.models import Permission, Role

        await self.list_permissions()

        dup = await self.session.scalar(
            select(Role.id).where(
                Role.organization_id == self.actor.organization_id,
                Role.name == name,
            )
        )
        if dup:
            raise ConflictError(f"A role named '{name}' already exists in your organization")

        perms = (
            await self.session.scalars(
                select(Permission).where(Permission.code.in_(permission_codes))
            )
        ).all()

        role = Role(
            organization_id=self.actor.organization_id,
            name=name,
            description=description,
            is_system_role=False,
            permissions=list(perms),
        )
        self.session.add(role)
        await self.session.commit()

        query = select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
        return await self.session.scalar(query)

    async def update_role_permissions(
        self, role_id: uuid.UUID, permission_codes: list[str]
    ) -> Role:
        from sqlalchemy import or_, select
        from sqlalchemy.orm import selectinload
        from app.core.exceptions import ForbiddenError, NotFoundError
        from app.models import Permission, Role

        await self.list_permissions()

        query = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(
                Role.id == role_id,
                or_(
                    Role.organization_id == self.actor.organization_id,
                    Role.is_system_role.is_(True),
                ),
            )
        )
        role = await self.session.scalar(query)
        if not role:
            raise NotFoundError("Role not found")
        if role.is_system_role and not self.actor.is_superuser:
            raise ForbiddenError("System roles can only be modified by superadmins")

        perms = (
            await self.session.scalars(
                select(Permission).where(Permission.code.in_(permission_codes))
            )
        ).all()
        role.permissions = list(perms)
        await self.session.commit()

        return role

    async def update(
        self, user_id: uuid.UUID, body: UserUpdate, request: Request | None = None
    ) -> UserRead:
        from datetime import UTC, datetime
        from sqlalchemy import or_, select
        from app.core.exceptions import ForbiddenError
        from app.models import Role

        user = await self.repository.get(user_id)
        if user is None:
            raise NotFoundError("User not found")

        if body.first_name is not None:
            user.first_name = body.first_name
        if body.last_name is not None:
            user.last_name = body.last_name
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.is_superuser is not None:
            if not self.actor.is_superuser:
                raise ForbiddenError("Only superadmins can grant or revoke superuser status")
            user.is_superuser = body.is_superuser
        if body.is_field_portal_only is not None:
            user.is_field_portal_only = body.is_field_portal_only

        if body.role_ids is not None:
            roles = (
                await self.session.scalars(
                    select(Role).where(
                        Role.id.in_(body.role_ids),
                        or_(
                            Role.organization_id == self.actor.organization_id,
                            Role.is_system_role.is_(True),
                        ),
                    )
                )
            ).all()
            user.roles = list(roles)

        user.updated_at = datetime.now(UTC)
        await self.session.commit()
        loaded = await self.repository.get(user_id)
        return UserRead.model_validate(loaded or user)


