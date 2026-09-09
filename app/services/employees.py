import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    AuditLog,
    Department,
    Employee,
    EmployeeAssetAuthorization,
    EmployeeAssignment,
    EmployeeDocument,
    EmployeeEmergencyContact,
    EmployeeFamilyMember,
    EmployeeLicense,
    EmployeeQualification,
    EmployeeResume,
    EmployeeRotation,
    EmployeeSkill,
    EmployeeTrainingRecord,
    Location,
    Position,
    Project,
    RotationPattern,
    Skill,
    User,
)
from app.models.employee import (
    AssignmentStatus,
    AvailabilityStatus,
    ComplianceStatus,
    EmploymentStatus,
    RotationStatus,
    TrainingStatus,
)
from app.repositories.base import organization_query
from app.schemas.common import Page
from app.schemas.employee import (
    ActivityEntry,
    ComplianceIssue,
    ComplianceResult,
    DepartmentRead,
    EmployeeAssetAuthorizationRead,
    EmployeeAssignmentCreate,
    EmployeeAssignmentRead,
    EmployeeAssignmentUpdate,
    EmployeeBasic,
    EmployeeCreate,
    EmployeeDocumentRead,
    EmployeeEmergencyContactRead,
    EmployeeFamilyRead,
    EmployeeFull,
    EmployeeLicenseRead,
    EmployeeOverview,
    EmployeeQualificationRead,
    EmployeeRead,
    EmployeeResumeRead,
    EmployeeRotationRead,
    EmployeeSkillRead,
    EmployeeTrainingRead,
    EmployeeTransferRequest,
    EmployeeUpdate,
    FamilySummary,
    ManpowerGroup,
    ManpowerSummary,
    PositionRead,
    WorkforceDashboard,
)
from app.services.audit import RequestMetadata, record_audit, request_metadata
from app.services.counters import next_business_number

REQUIRED_EMPLOYMENT_DOCUMENTS = frozenset(
    {"NATIONAL_ID", "EMPLOYMENT_CONTRACT", "MEDICAL_CERTIFICATE"}
)
EXPIRY_WARNING_DAYS = 30
CONTRACT_WARNING_DAYS = 60
INACTIVE_STATUSES = frozenset({"EXITED", "RESIGNED", "TERMINATED", "RETIRED", "DECEASED"})

SORTABLE_FIELDS = {
    "created_at": Employee.created_at,
    "last_name": Employee.last_name,
    "first_name": Employee.first_name,
    "hire_date": Employee.hire_date,
    "employee_number": Employee.employee_number,
}


def _meta(request: Request | None) -> RequestMetadata:
    if request is None:
        return {"ip_address": None, "user_agent": None}
    return request_metadata(request)


async def availability_map(
    session: AsyncSession, organization_id: uuid.UUID, employees: Sequence[Employee]
) -> dict[uuid.UUID, AvailabilityStatus]:
    """Derive availability per employee (batch). Never stored; always computed."""
    today = date.today()
    ids = [e.id for e in employees]
    result: dict[uuid.UUID, AvailabilityStatus] = {}
    if not ids:
        return result
    active_assignments = {
        row.employee_id
        for row in (
            await session.scalars(
                organization_query(EmployeeAssignment, organization_id).where(
                    EmployeeAssignment.employee_id.in_(ids),
                    EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        ).all()
    }
    rotations = (
        await session.scalars(
            organization_query(EmployeeRotation, organization_id).where(
                EmployeeRotation.employee_id.in_(ids),
                EmployeeRotation.status.in_([RotationStatus.ON_SITE, RotationStatus.OFF_ROTATION]),
            )
        )
    ).all()
    rotation_state: dict[uuid.UUID, str] = {}
    for rotation in rotations:
        if rotation.work_start_date <= today <= rotation.work_end_date:
            rotation_state[rotation.employee_id] = "ON_SITE"
        elif rotation.off_start_date <= today <= rotation.off_end_date:
            rotation_state.setdefault(rotation.employee_id, "OFF_ROTATION")
        elif rotation.status == RotationStatus.OFF_ROTATION:
            rotation_state.setdefault(rotation.employee_id, "OFF_ROTATION")
    training_ids = {
        row.employee_id
        for row in (
            await session.scalars(
                organization_query(EmployeeTrainingRecord, organization_id).where(
                    EmployeeTrainingRecord.employee_id.in_(ids),
                    EmployeeTrainingRecord.status == TrainingStatus.IN_PROGRESS,
                )
            )
        ).all()
    }
    for employee in employees:
        status = employee.employment_status.value if employee.employment_status else ""
        if not employee.is_active or employee.archived_at is not None:
            result[employee.id] = AvailabilityStatus.UNAVAILABLE
        elif status == EmploymentStatus.SUSPENDED.value:
            result[employee.id] = AvailabilityStatus.SUSPENDED
        elif status in INACTIVE_STATUSES:
            result[employee.id] = AvailabilityStatus.UNAVAILABLE
        elif status == EmploymentStatus.ON_LEAVE.value:
            result[employee.id] = AvailabilityStatus.ON_LEAVE
        elif rotation_state.get(employee.id) == "OFF_ROTATION":
            result[employee.id] = AvailabilityStatus.OFF_ROTATION
        elif employee.id in active_assignments or rotation_state.get(employee.id) == "ON_SITE":
            result[employee.id] = AvailabilityStatus.ASSIGNED
        elif employee.id in training_ids:
            result[employee.id] = AvailabilityStatus.TRAINING
        elif status == EmploymentStatus.OFF_ROTATION.value:
            result[employee.id] = AvailabilityStatus.OFF_ROTATION
        else:
            result[employee.id] = AvailabilityStatus.AVAILABLE
    return result


class EmployeeService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def _scope(self) -> Select[tuple[Employee]]:
        return organization_query(Employee, self.actor.organization_id)

    async def _get_or_404(self, employee_id: uuid.UUID) -> Employee:
        employee = (
            await self.session.scalars(self._scope().where(Employee.id == employee_id))
        ).one_or_none()
        if employee is None:
            raise NotFoundError("Employee not found")
        return employee

    def operational_read(self, read: EmployeeRead) -> EmployeeRead:
        from app.core.dependencies import scoped_roles

        if self.actor.is_superuser or any(
            p.code == "employees.read_full"
            for role in scoped_roles(self.actor)
            for p in role.permissions
        ):
            return read
        private = (
            "gender date_of_birth nationality marital_status personal_email secondary_phone "
            "residential_address city county_or_region country "
            "probation_end_date confirmation_date "
            "contract_start_date contract_end_date termination_date termination_reason bio notes"
        ).split()
        return read.model_copy(update={key: None for key in private})

    async def get(self, employee_id: uuid.UUID) -> EmployeeRead:
        employee = await self._get_or_404(employee_id)
        read = EmployeeRead.model_validate(employee)
        avail = await availability_map(self.session, self.actor.organization_id, [employee])
        read.availability_status = avail.get(employee.id)
        return self.operational_read(read)

    async def get_full(self, employee_id: uuid.UUID) -> EmployeeFull:
        employee = await self._get_or_404(employee_id)
        full = EmployeeFull.model_validate(employee)
        avail = await availability_map(self.session, self.actor.organization_id, [employee])
        full.availability_status = avail.get(employee.id)
        full.family = [
            EmployeeFamilyRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeFamilyMember, self.actor.organization_id)
                    .where(EmployeeFamilyMember.employee_id == employee_id)
                    .order_by(EmployeeFamilyMember.full_name)
                )
            ).all()
        ]
        full.emergency_contacts = [
            EmployeeEmergencyContactRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeEmergencyContact, self.actor.organization_id)
                    .where(EmployeeEmergencyContact.employee_id == employee_id)
                    .order_by(
                        EmployeeEmergencyContact.is_primary.desc(),
                        EmployeeEmergencyContact.priority,
                    )
                )
            ).all()
        ]
        return full

    async def list(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        department: str | None = None,
        department_id: uuid.UUID | None = None,
        position_id: uuid.UUID | None = None,
        employment_type: str | None = None,
        employment_status: EmploymentStatus | None = None,
        availability_status: AvailabilityStatus | None = None,
        job_title: str | None = None,
        project_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        supervisor_id: uuid.UUID | None = None,
        skill_id: uuid.UUID | None = None,
        license_type: str | None = None,
        rotation_status: RotationStatus | None = None,
        is_active: bool | None = None,
        unassigned_only: bool = False,
        document_expiring_within_days: int | None = None,
        contract_expiring_within_days: int | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "asc",
    ) -> Page[EmployeeRead]:
        query = self._scope()
        if search:
            like = f"%{search}%"
            query = query.where(
                or_(
                    Employee.employee_number.ilike(like),
                    Employee.first_name.ilike(like),
                    Employee.middle_name.ilike(like),
                    Employee.last_name.ilike(like),
                    Employee.preferred_name.ilike(like),
                    Employee.personal_email.ilike(like),
                    Employee.work_email.ilike(like),
                    Employee.primary_phone.ilike(like),
                )
            )
        if department:
            query = query.where(Employee.department == department)
        if department_id is not None:
            query = query.where(Employee.department_id == department_id)
        if position_id is not None:
            query = query.where(Employee.position_id == position_id)
        if employment_type is not None:
            query = query.where(Employee.employment_type == employment_type)
        if employment_status is not None:
            query = query.where(Employee.employment_status == employment_status)
        if job_title:
            query = query.where(Employee.job_title.ilike(f"%{job_title}%"))
        if supervisor_id is not None:
            query = query.where(Employee.supervisor_id == supervisor_id)
        if is_active is not None:
            query = query.where(Employee.is_active == is_active)
        if skill_id is not None:
            query = query.where(
                select(EmployeeSkill.id)
                .where(
                    EmployeeSkill.organization_id == self.actor.organization_id,
                    EmployeeSkill.employee_id == Employee.id,
                    EmployeeSkill.skill_id == skill_id,
                )
                .exists()
            )
        if license_type is not None:
            query = query.where(
                select(EmployeeLicense.id)
                .where(
                    EmployeeLicense.organization_id == self.actor.organization_id,
                    EmployeeLicense.employee_id == Employee.id,
                    EmployeeLicense.license_type == license_type,
                    EmployeeLicense.is_active == True,  # noqa: E712
                )
                .exists()
            )
        if rotation_status is not None:
            query = query.where(
                select(EmployeeRotation.id)
                .where(
                    EmployeeRotation.organization_id == self.actor.organization_id,
                    EmployeeRotation.employee_id == Employee.id,
                    EmployeeRotation.status == rotation_status,
                )
                .exists()
            )
        if document_expiring_within_days is not None:
            cutoff = date.today() + timedelta(days=document_expiring_within_days)
            query = query.where(
                select(EmployeeDocument.id)
                .where(
                    EmployeeDocument.organization_id == self.actor.organization_id,
                    EmployeeDocument.employee_id == Employee.id,
                    EmployeeDocument.expiry_date.is_not(None),
                    EmployeeDocument.expiry_date <= cutoff,
                    EmployeeDocument.is_active == True,  # noqa: E712
                )
                .exists()
            )
        if contract_expiring_within_days is not None:
            cutoff = date.today() + timedelta(days=contract_expiring_within_days)
            query = query.where(
                Employee.contract_end_date.is_not(None),
                Employee.contract_end_date <= cutoff,
            )
        assignment_filter = project_id is not None or location_id is not None or unassigned_only
        if assignment_filter:
            active = select(EmployeeAssignment.employee_id).where(
                EmployeeAssignment.organization_id == self.actor.organization_id,
                EmployeeAssignment.status == AssignmentStatus.ACTIVE,
            )
            if project_id is not None:
                active = active.where(EmployeeAssignment.project_id == project_id)
            if location_id is not None:
                active = active.where(EmployeeAssignment.location_id == location_id)
            assigned_ids = set((await self.session.scalars(active)).all())
            if unassigned_only and project_id is None and location_id is None:
                if assigned_ids:
                    query = query.where(Employee.id.notin_(assigned_ids))
            elif project_id is not None or location_id is not None:
                if not assigned_ids:
                    return Page(items=[], total=0, page=page, page_size=page_size, pages=0)
                query = query.where(Employee.id.in_(assigned_ids))
            elif unassigned_only:
                pass
        order_column = SORTABLE_FIELDS.get(sort_by, Employee.created_at)
        order = order_column.desc() if sort_dir == "desc" else order_column.asc()
        if availability_status is None:
            total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await self.session.scalars(
                    query.order_by(order, Employee.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        else:
            candidates = (await self.session.scalars(query.order_by(order, Employee.id))).all()
            avail = await availability_map(self.session, self.actor.organization_id, candidates)
            matching = [e for e in candidates if avail.get(e.id) == availability_status]
            total = len(matching)
            rows = matching[(page - 1) * page_size : page * page_size]
            return await self._to_page(rows, avail, total, page, page_size)
        avail_map = await availability_map(self.session, self.actor.organization_id, list(rows))
        return await self._to_page(list(rows), avail_map, total or 0, page, page_size)

    async def _to_page(
        self,
        rows: Sequence[Employee],
        avail: dict[uuid.UUID, AvailabilityStatus],
        total: int,
        page: int,
        page_size: int,
    ) -> Page[EmployeeRead]:
        items = []
        for row in rows:
            read = EmployeeRead.model_validate(row)
            read.availability_status = avail.get(row.id)
            items.append(self.operational_read(read))
        return Page(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if page_size else 0,
        )

    async def available(
        self,
        page: int,
        page_size: int,
        position_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        skill_id: uuid.UUID | None = None,
        license_type: str | None = None,
        asset_category_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> Page[EmployeeBasic]:
        """Employees deployable now, with mobilization-planning filters."""
        assigned_to_project: set[uuid.UUID] = set()
        if project_id is not None:
            assigned_to_project = set(
                (
                    await self.session.scalars(
                        select(EmployeeAssignment.employee_id).where(
                            EmployeeAssignment.organization_id == self.actor.organization_id,
                            EmployeeAssignment.project_id == project_id,
                            EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                        )
                    )
                ).all()
            )
        query = self._scope().where(Employee.is_active == True)  # noqa: E712
        if position_id is not None:
            query = query.where(Employee.position_id == position_id)
        if department_id is not None:
            query = query.where(Employee.department_id == department_id)
        if skill_id is not None:
            query = query.where(
                select(EmployeeSkill.id)
                .where(
                    EmployeeSkill.organization_id == self.actor.organization_id,
                    EmployeeSkill.employee_id == Employee.id,
                    EmployeeSkill.skill_id == skill_id,
                )
                .exists()
            )
        if license_type is not None:
            query = query.where(
                select(EmployeeLicense.id)
                .where(
                    EmployeeLicense.organization_id == self.actor.organization_id,
                    EmployeeLicense.employee_id == Employee.id,
                    EmployeeLicense.license_type == license_type,
                    EmployeeLicense.is_active == True,  # noqa: E712
                )
                .exists()
            )
        if asset_category_id is not None:
            query = query.where(
                select(EmployeeAssetAuthorization.id)
                .where(
                    EmployeeAssetAuthorization.organization_id == self.actor.organization_id,
                    EmployeeAssetAuthorization.employee_id == Employee.id,
                    EmployeeAssetAuthorization.asset_category_id == asset_category_id,
                    EmployeeAssetAuthorization.status == "ACTIVE",
                )
                .exists()
            )
        candidates = (await self.session.scalars(query)).all()
        avail = await availability_map(self.session, self.actor.organization_id, candidates)
        matching = [
            e
            for e in candidates
            if avail.get(e.id) == AvailabilityStatus.AVAILABLE and e.id not in assigned_to_project
        ]
        total = len(matching)
        page_rows = matching[(page - 1) * page_size : page * page_size]
        basics = [await self._to_basic(e, avail.get(e.id)) for e in page_rows]
        return Page(
            items=basics,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if page_size else 0,
        )

    async def _to_basic(
        self, employee: Employee, availability: AvailabilityStatus | None
    ) -> EmployeeBasic:
        current = (
            await self.session.scalars(
                organization_query(EmployeeAssignment, self.actor.organization_id)
                .where(
                    EmployeeAssignment.employee_id == employee.id,
                    EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                )
                .order_by(EmployeeAssignment.start_date.desc())
                .limit(1)
            )
        ).first()
        project_name: str | None = None
        location_name: str | None = None
        project_id = current.project_id if current else None
        location_id = current.location_id if current else None
        if project_id is not None:
            project = await self.session.get(Project, project_id)
            if project is not None and project.organization_id == self.actor.organization_id:
                project_name = project.name
        if location_id is not None:
            location = await self.session.get(Location, location_id)
            if location is not None and location.organization_id == self.actor.organization_id:
                location_name = location.name
        return EmployeeBasic(
            id=employee.id,
            organization_id=employee.organization_id,
            employee_number=employee.employee_number,
            full_name=" ".join(
                part for part in [employee.first_name, employee.last_name] if part
            ).strip(),
            profile_photo_url=employee.profile_photo_url,
            job_title=employee.job_title,
            position_id=employee.position_id,
            department_id=employee.department_id,
            department=employee.department,
            primary_phone=employee.primary_phone,
            employment_status=employee.employment_status,
            availability_status=availability,
            current_project_id=project_id,
            current_project_name=project_name,
            current_location_id=location_id,
            current_location_name=location_name,
        )

    async def create(self, body: EmployeeCreate, request: Request | None = None) -> EmployeeRead:
        try:
            await self._check_master_refs(
                body.supervisor_id,
                body.department_id,
                body.position_id,
                body.home_location_id,
                None,
            )
            self._check_master_dates(body)
            if body.work_email:
                await self._check_work_email_unique(body.work_email, None)
            number = await next_business_number(
                self.session, self.actor.organization_id, "employee"
            )
            employee = Employee(
                organization_id=self.actor.organization_id,
                employee_number=number,
                first_name=body.first_name,
                middle_name=body.middle_name,
                last_name=body.last_name,
                preferred_name=body.preferred_name,
                gender=body.gender,
                date_of_birth=body.date_of_birth,
                nationality=body.nationality,
                marital_status=body.marital_status,
                personal_email=str(body.personal_email).lower() if body.personal_email else None,
                work_email=str(body.work_email).lower() if body.work_email else None,
                primary_phone=body.primary_phone,
                secondary_phone=body.secondary_phone,
                residential_address=body.residential_address,
                city=body.city,
                county_or_region=body.county_or_region,
                country=body.country,
                department_id=body.department_id,
                position_id=body.position_id,
                department=body.department,
                job_title=body.job_title,
                employment_type=body.employment_type,
                employment_status=body.employment_status,
                hire_date=body.hire_date,
                probation_end_date=body.probation_end_date,
                confirmation_date=body.confirmation_date,
                contract_start_date=body.contract_start_date,
                contract_end_date=body.contract_end_date,
                termination_date=body.termination_date,
                termination_reason=body.termination_reason,
                supervisor_id=body.supervisor_id,
                home_location_id=body.home_location_id,
                profile_photo_url=str(body.profile_photo_url) if body.profile_photo_url else None,
                bio=body.bio,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            if employee.department is None and employee.department_id is not None:
                department = await self.session.get(Department, employee.department_id)
                if department is not None:
                    employee.department = department.name
            self.session.add(employee)
            await self.session.flush()
            from app.services.hr import link_account

            await link_account(self.session, self.actor, employee)
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.created",
                entity_type="employee",
                entity_id=employee.id,
                new_values={"employee_number": number, "job_title": body.job_title},
                **_meta(request),
            )
            await self.session.commit()
            read = EmployeeRead.model_validate(employee)
            avail = await availability_map(self.session, self.actor.organization_id, [employee])
            read.availability_status = avail.get(employee.id)
            return read
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, employee_id: uuid.UUID, body: EmployeeUpdate, request: Request | None = None
    ) -> EmployeeRead:
        try:
            employee = await self._get_or_404(employee_id)
            data = body.model_dump(exclude_unset=True)
            if employee.user_id and any(
                key in data and data[key] != getattr(employee, key)
                for key in ("work_email", "personal_email")
            ):
                raise ConflictError(
                    "Linked account emails must be changed through the superadmin account workflow"
                )
            if "supervisor_id" in data and data["supervisor_id"] is not None:
                if data["supervisor_id"] == employee.id:
                    raise ValidationError("An employee cannot supervise themselves")
            await self._check_master_refs(
                data.get("supervisor_id", employee.supervisor_id),
                data.get("department_id", employee.department_id),
                data.get("position_id", employee.position_id),
                data.get("home_location_id", employee.home_location_id),
                employee.id,
            )
            if "work_email" in data and data["work_email"] is not None:
                data["work_email"] = str(data["work_email"]).lower()
                await self._check_work_email_unique(data["work_email"], employee.id)
            if "personal_email" in data and data["personal_email"] is not None:
                data["personal_email"] = str(data["personal_email"]).lower()
            hire = data.get("hire_date", employee.hire_date)
            term = data.get("termination_date", employee.termination_date)
            if hire and term and term < hire:
                raise ValidationError("Termination date cannot precede hire date")
            contract_start = data.get("contract_start_date", employee.contract_start_date)
            contract_end = data.get("contract_end_date", employee.contract_end_date)
            if contract_start and contract_end and contract_end < contract_start:
                raise ValidationError("Contract end cannot precede contract start")
            for key, value in data.items():
                setattr(employee, key, value)
            employee.updated_by_id = self.actor.id
            employee.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.updated",
                entity_type="employee",
                entity_id=employee.id,
                new_values={"employee_number": employee.employee_number},
                **_meta(request),
            )
            await self.session.commit()
            read = EmployeeRead.model_validate(employee)
            avail = await availability_map(self.session, self.actor.organization_id, [employee])
            read.availability_status = avail.get(employee.id)
            return read
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def archive(self, employee_id: uuid.UUID, request: Request | None = None) -> EmployeeRead:
        try:
            employee = await self._get_or_404(employee_id)
            if employee.archived_at is not None or not employee.is_active:
                raise ConflictError("Employee is already archived")
            employee.is_active = False
            employee.archived_at = datetime.now(UTC)
            employee.updated_by_id = self.actor.id
            employee.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.archived",
                entity_type="employee",
                entity_id=employee.id,
                new_values={"employee_number": employee.employee_number},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeRead.model_validate(employee)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def restore(self, employee_id: uuid.UUID, request: Request | None = None) -> EmployeeRead:
        try:
            employee = await self._get_or_404(employee_id)
            if employee.archived_at is None and employee.is_active:
                raise ConflictError("Employee is not archived")
            employee.is_active = True
            employee.archived_at = None
            employee.updated_by_id = self.actor.id
            employee.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.restored",
                entity_type="employee",
                entity_id=employee.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeRead.model_validate(employee)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _check_master_refs(
        self,
        supervisor_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        position_id: uuid.UUID | None,
        home_location_id: uuid.UUID | None,
        self_id: uuid.UUID | None,
    ) -> None:
        if supervisor_id is not None:
            if supervisor_id == self_id and self_id is not None:
                raise ValidationError("An employee cannot supervise themselves")
            supervisor = (
                await self.session.scalars(self._scope().where(Employee.id == supervisor_id))
            ).one_or_none()
            if supervisor is None:
                raise NotFoundError("Supervisor not found")
        if department_id is not None:
            department = (
                await self.session.scalars(
                    organization_query(Department, self.actor.organization_id).where(
                        Department.id == department_id
                    )
                )
            ).one_or_none()
            if department is None:
                raise NotFoundError("Department not found")
        if position_id is not None:
            position = (
                await self.session.scalars(
                    organization_query(Position, self.actor.organization_id).where(
                        Position.id == position_id
                    )
                )
            ).one_or_none()
            if position is None:
                raise NotFoundError("Position not found")
        if home_location_id is not None:
            location = (
                await self.session.scalars(
                    organization_query(Location, self.actor.organization_id).where(
                        Location.id == home_location_id
                    )
                )
            ).one_or_none()
            if location is None:
                raise NotFoundError("Home location not found")

    async def _check_work_email_unique(self, work_email: str, self_id: uuid.UUID | None) -> None:
        query = self._scope().where(Employee.work_email == work_email.lower())
        if self_id is not None:
            query = query.where(Employee.id != self_id)
        if (await self.session.scalars(query)).first() is not None:
            raise ConflictError("Work email is already used in this organization")

    def _check_master_dates(self, body: EmployeeCreate) -> None:
        if body.termination_date and body.hire_date and body.termination_date < body.hire_date:
            raise ValidationError("Termination date cannot precede hire date")
        if (
            body.contract_end_date
            and body.contract_start_date
            and body.contract_end_date < body.contract_start_date
        ):
            raise ValidationError("Contract end cannot precede contract start")

    # ---- assignments ----

    async def list_assignments(self, employee_id: uuid.UUID) -> Sequence[EmployeeAssignmentRead]:
        await self._get_or_404(employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeAssignment, self.actor.organization_id)
                .where(EmployeeAssignment.employee_id == employee_id)
                .order_by(EmployeeAssignment.start_date.desc())
            )
        ).all()
        return [EmployeeAssignmentRead.model_validate(row) for row in rows]

    async def get_assignment(self, assignment_id: uuid.UUID) -> EmployeeAssignmentRead:
        assignment = (
            await self.session.scalars(
                organization_query(EmployeeAssignment, self.actor.organization_id).where(
                    EmployeeAssignment.id == assignment_id
                )
            )
        ).one_or_none()
        if assignment is None:
            raise NotFoundError("Assignment not found")
        return EmployeeAssignmentRead.model_validate(assignment)

    async def create_assignment(
        self,
        employee_id: uuid.UUID,
        body: EmployeeAssignmentCreate,
        request: Request | None = None,
    ) -> EmployeeAssignmentRead:
        try:
            employee = await self._get_or_404(employee_id)
            if not employee.is_active or employee.archived_at is not None:
                raise ConflictError("Cannot assign an archived or inactive employee")
            await self._check_assignment_refs(body, employee_id, None)
            number = await next_business_number(
                self.session, self.actor.organization_id, "assignment"
            )
            assignment = EmployeeAssignment(
                organization_id=self.actor.organization_id,
                assignment_number=number,
                employee_id=employee_id,
                project_id=body.project_id,
                location_id=body.location_id,
                position_id=body.position_id,
                role_on_project=body.role_on_project,
                supervisor_id=body.supervisor_id,
                assignment_type=body.assignment_type,
                start_date=body.start_date,
                end_date=body.end_date,
                is_primary=body.is_primary,
                status=body.status,
                rotation_pattern_id=body.rotation_pattern_id,
                rotation_pattern=body.rotation_pattern,
                mobilization_date=body.mobilization_date,
                demobilization_date=body.demobilization_date,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(assignment)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.assigned",
                entity_type="employee_assignment",
                entity_id=assignment.id,
                new_values={
                    "assignment_number": number,
                    "employee_id": str(employee_id),
                    "project_id": str(body.project_id),
                },
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeAssignmentRead.model_validate(assignment)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _check_assignment_refs(
        self, body: EmployeeAssignmentCreate, employee_id: uuid.UUID, self_id: uuid.UUID | None
    ) -> None:
        project = (
            await self.session.scalars(
                select(Project).where(
                    Project.id == body.project_id,
                    Project.organization_id == self.actor.organization_id,
                )
            )
        ).one_or_none()
        if project is None:
            raise NotFoundError("Project not found")
        if body.location_id is not None:
            location = (
                await self.session.scalars(
                    select(Location).where(
                        Location.id == body.location_id,
                        Location.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if location is None:
                raise NotFoundError("Location not found")
            if location.project_id is not None and location.project_id != body.project_id:
                raise ValidationError("Location does not belong to the given project")
        if body.position_id is not None:
            position = (
                await self.session.scalars(
                    select(Position).where(
                        Position.id == body.position_id,
                        Position.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if position is None:
                raise NotFoundError("Position not found")
        if body.supervisor_id is not None:
            supervisor = (
                await self.session.scalars(self._scope().where(Employee.id == body.supervisor_id))
            ).one_or_none()
            if supervisor is None:
                raise NotFoundError("Supervisor not found")
        if body.rotation_pattern_id is not None:
            pattern = (
                await self.session.scalars(
                    select(RotationPattern).where(
                        RotationPattern.id == body.rotation_pattern_id,
                        RotationPattern.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if pattern is None:
                raise NotFoundError("Rotation pattern not found")
        if body.end_date is not None and body.end_date < body.start_date:
            raise ValidationError("Assignment end date cannot precede start date")
        if body.status == AssignmentStatus.ACTIVE and body.is_primary:
            await self._reject_primary_conflict(employee_id, self_id)

    async def _reject_primary_conflict(
        self, employee_id: uuid.UUID, self_id: uuid.UUID | None
    ) -> None:
        query = organization_query(EmployeeAssignment, self.actor.organization_id).where(
            EmployeeAssignment.employee_id == employee_id,
            EmployeeAssignment.status == AssignmentStatus.ACTIVE,
            EmployeeAssignment.is_primary == True,  # noqa: E712
        )
        if self_id is not None:
            query = query.where(EmployeeAssignment.id != self_id)
        if (await self.session.scalars(query)).first() is not None:
            raise ConflictError(
                "Employee already has an active primary assignment; complete it first"
            )

    async def update_assignment(
        self,
        assignment_id: uuid.UUID,
        body: EmployeeAssignmentUpdate,
        request: Request | None = None,
    ) -> EmployeeAssignmentRead:
        try:
            assignment = (
                await self.session.scalars(
                    organization_query(EmployeeAssignment, self.actor.organization_id).where(
                        EmployeeAssignment.id == assignment_id
                    )
                )
            ).one_or_none()
            if assignment is None:
                raise NotFoundError("Assignment not found")
            data = body.model_dump(exclude_unset=True)
            merged = EmployeeAssignmentCreate(
                project_id=assignment.project_id,
                location_id=data.get("location_id", assignment.location_id),
                position_id=data.get("position_id", assignment.position_id),
                role_on_project=data.get("role_on_project", assignment.role_on_project),
                supervisor_id=data.get("supervisor_id", assignment.supervisor_id),
                assignment_type=data.get("assignment_type", assignment.assignment_type),
                start_date=data.get("start_date", assignment.start_date),
                end_date=data.get("end_date", assignment.end_date),
                is_primary=data.get("is_primary", assignment.is_primary),
                status=data.get("status", assignment.status),
                rotation_pattern_id=data.get("rotation_pattern_id", assignment.rotation_pattern_id),
                rotation_pattern=data.get("rotation_pattern", assignment.rotation_pattern),
                mobilization_date=data.get("mobilization_date", assignment.mobilization_date),
                demobilization_date=data.get("demobilization_date", assignment.demobilization_date),
            )
            await self._check_assignment_refs(merged, assignment.employee_id, assignment.id)
            for key, value in data.items():
                setattr(assignment, key, value)
            assignment.updated_by_id = self.actor.id
            assignment.updated_at = datetime.now(UTC)
            completed = data.get("status", assignment.status) == AssignmentStatus.COMPLETED
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.assignment_completed"
                if completed
                else "employee.assignment_updated",
                entity_type="employee_assignment",
                entity_id=assignment.id,
                new_values={"status": str(data.get("status", assignment.status))},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeAssignmentRead.model_validate(assignment)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def complete_assignment(
        self, assignment_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeAssignmentRead:
        return await self.update_assignment(
            assignment_id,
            EmployeeAssignmentUpdate(status=AssignmentStatus.COMPLETED, end_date=date.today()),
            request,
        )

    async def cancel_assignment(
        self, assignment_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeAssignmentRead:
        return await self.update_assignment(
            assignment_id, EmployeeAssignmentUpdate(status=AssignmentStatus.CANCELLED), request
        )

    async def transfer(
        self,
        employee_id: uuid.UUID,
        body: EmployeeTransferRequest,
        request: Request | None = None,
    ) -> EmployeeAssignmentRead:
        """Complete the current primary assignment and open a new one atomically."""
        try:
            employee = await self._get_or_404(employee_id)
            if not employee.is_active or employee.archived_at is not None:
                raise ConflictError("Cannot transfer an archived or inactive employee")
            current = (
                await self.session.scalars(
                    organization_query(EmployeeAssignment, self.actor.organization_id).where(
                        EmployeeAssignment.employee_id == employee_id,
                        EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                        EmployeeAssignment.is_primary == True,  # noqa: E712
                    )
                )
            ).first()
            if current is not None:
                current.status = AssignmentStatus.COMPLETED
                current.end_date = body.start_date
                current.updated_by_id = self.actor.id
                current.updated_at = datetime.now(UTC)
                record_audit(
                    self.session,
                    organization_id=self.actor.organization_id,
                    actor_user_id=self.actor.id,
                    action="employee.assignment_completed",
                    entity_type="employee_assignment",
                    entity_id=current.id,
                    new_values={"transfer_to": str(body.project_id)},
                    **_meta(request),
                )
                await self.session.flush()
            created = EmployeeAssignmentCreate(
                project_id=body.project_id,
                location_id=body.location_id,
                position_id=body.position_id,
                role_on_project=body.role_on_project,
                supervisor_id=body.supervisor_id,
                assignment_type=body.assignment_type,
                start_date=body.start_date,
                is_primary=True,
                status=AssignmentStatus.ACTIVE,
                rotation_pattern_id=body.rotation_pattern_id,
                notes=body.notes,
            )
            await self._check_assignment_refs(created, employee_id, current.id if current else None)
            number = await next_business_number(
                self.session, self.actor.organization_id, "assignment"
            )
            assignment = EmployeeAssignment(
                organization_id=self.actor.organization_id,
                assignment_number=number,
                employee_id=employee_id,
                project_id=created.project_id,
                location_id=created.location_id,
                position_id=created.position_id,
                role_on_project=created.role_on_project,
                supervisor_id=created.supervisor_id,
                assignment_type=created.assignment_type,
                start_date=created.start_date,
                is_primary=True,
                status=AssignmentStatus.ACTIVE,
                rotation_pattern_id=created.rotation_pattern_id,
                notes=created.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(assignment)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.transferred",
                entity_type="employee_assignment",
                entity_id=assignment.id,
                new_values={
                    "assignment_number": number,
                    "project_id": str(body.project_id),
                    "from_assignment_id": str(current.id) if current else None,
                },
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeAssignmentRead.model_validate(assignment)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- compliance ----

    async def compliance(self, employee: Employee) -> ComplianceResult:
        today = date.today()
        issues: list[ComplianceIssue] = []
        licenses = (
            await self.session.scalars(
                organization_query(EmployeeLicense, self.actor.organization_id).where(
                    EmployeeLicense.employee_id == employee.id,
                    EmployeeLicense.is_active == True,  # noqa: E712
                )
            )
        ).all()
        for lic in licenses:
            if lic.expiry_date and lic.expiry_date < today:
                issues.append(
                    ComplianceIssue(
                        rule="expired_licence",
                        severity="error",
                        message=f"{lic.license_type.value} expired on {lic.expiry_date}",
                    )
                )
            elif lic.expiry_date and lic.expiry_date <= today + timedelta(days=EXPIRY_WARNING_DAYS):
                issues.append(
                    ComplianceIssue(
                        rule="expiring_licence",
                        severity="warning",
                        message=f"{lic.license_type.value} expires on {lic.expiry_date}",
                    )
                )
        documents = (
            await self.session.scalars(
                organization_query(EmployeeDocument, self.actor.organization_id).where(
                    EmployeeDocument.employee_id == employee.id,
                    EmployeeDocument.is_active == True,  # noqa: E712
                )
            )
        ).all()
        for doc in documents:
            if doc.expiry_date and doc.expiry_date < today:
                issues.append(
                    ComplianceIssue(
                        rule="expired_document",
                        severity="error",
                        message=f"{doc.title} expired on {doc.expiry_date}",
                    )
                )
            elif doc.expiry_date and doc.expiry_date <= today + timedelta(days=EXPIRY_WARNING_DAYS):
                issues.append(
                    ComplianceIssue(
                        rule="expiring_document",
                        severity="warning",
                        message=f"{doc.title} expires on {doc.expiry_date}",
                    )
                )
        present_types = {d.document_type.value for d in documents if d.is_active}
        for required in sorted(REQUIRED_EMPLOYMENT_DOCUMENTS - present_types):
            issues.append(
                ComplianceIssue(
                    rule="missing_required_document",
                    severity="error",
                    message=f"Missing required document: {required}",
                )
            )
        contacts = (
            await self.session.scalars(
                organization_query(EmployeeEmergencyContact, self.actor.organization_id).where(
                    EmployeeEmergencyContact.employee_id == employee.id,
                    EmployeeEmergencyContact.is_active == True,  # noqa: E712
                )
            )
        ).all()
        if not contacts:
            issues.append(
                ComplianceIssue(
                    rule="missing_emergency_contact",
                    severity="warning",
                    message="No emergency contact on file",
                )
            )
        if any(i.severity == "error" for i in issues):
            status = ComplianceStatus.NON_COMPLIANT
        elif issues:
            status = ComplianceStatus.WARNING
        else:
            status = ComplianceStatus.COMPLIANT
        return ComplianceResult(status=status, issues=issues)

    # ---- overview ----

    async def overview(self, employee_id: uuid.UUID) -> EmployeeOverview:
        employee = await self._get_or_404(employee_id)
        avail = await availability_map(self.session, self.actor.organization_id, [employee])
        availability = avail.get(employee.id, AvailabilityStatus.UNAVAILABLE)
        department = None
        if employee.department_id is not None:
            department = await self.session.get(Department, employee.department_id)
        position = None
        if employee.position_id is not None:
            position = await self.session.get(Position, employee.position_id)
        supervisor = None
        if employee.supervisor_id is not None:
            supervisor = (
                await self.session.scalars(
                    self._scope().where(Employee.id == employee.supervisor_id)
                )
            ).one_or_none()
        assignments = list(await self.list_assignments(employee_id))
        current = next((a for a in assignments if a.status == AssignmentStatus.ACTIVE), None)
        current_project_name: str | None = None
        current_location_name: str | None = None
        if current is not None:
            current_project_name = await self._project_name(current.project_id)
            current_location_name = (
                await self._location_name(current.location_id) if current.location_id else None
            )
        current_rotation = await self._current_rotation(employee_id)
        emergency_contacts = [
            EmployeeEmergencyContactRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeEmergencyContact, self.actor.organization_id)
                    .where(EmployeeEmergencyContact.employee_id == employee_id)
                    .order_by(
                        EmployeeEmergencyContact.is_primary.desc(),
                        EmployeeEmergencyContact.priority,
                    )
                )
            ).all()
        ]
        primary_emergency = next((c for c in emergency_contacts if c.is_primary), None) or (
            emergency_contacts[0] if emergency_contacts else None
        )
        family = (
            await self.session.scalars(
                organization_query(EmployeeFamilyMember, self.actor.organization_id)
                .where(
                    EmployeeFamilyMember.employee_id == employee_id,
                    EmployeeFamilyMember.is_active == True,  # noqa: E712
                )
                .order_by(EmployeeFamilyMember.full_name)
            )
        ).all()
        spouse = next(
            (m.full_name for m in family if m.relationship_type.value == "SPOUSE" and m.is_active),
            None,
        )
        children = sum(1 for m in family if m.relationship_type.value == "CHILD" and m.is_active)
        dependants = sum(1 for m in family if m.is_dependent and m.is_active)
        next_of_kin = [m.full_name for m in family if m.is_next_of_kin and m.is_active]
        primary_nok = next(
            (m.full_name for m in family if m.is_primary_next_of_kin and m.is_active), None
        )
        current_resume = (
            await self.session.scalars(
                organization_query(EmployeeResume, self.actor.organization_id).where(
                    EmployeeResume.employee_id == employee_id,
                    EmployeeResume.is_current == True,  # noqa: E712
                    EmployeeResume.is_active == True,  # noqa: E712
                )
            )
        ).first()
        skills = [
            EmployeeSkillRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeSkill, self.actor.organization_id)
                    .where(EmployeeSkill.employee_id == employee_id)
                    .order_by(EmployeeSkill.created_at)
                )
            ).all()
        ]
        await self._fill_skill_names(skills)
        licenses = [
            EmployeeLicenseRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeLicense, self.actor.organization_id)
                    .where(
                        EmployeeLicense.employee_id == employee_id,
                        EmployeeLicense.is_active == True,  # noqa: E712
                    )
                    .order_by(EmployeeLicense.expiry_date)
                )
            ).all()
        ]
        qualifications = [
            EmployeeQualificationRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeQualification, self.actor.organization_id)
                    .where(
                        EmployeeQualification.employee_id == employee_id,
                        EmployeeQualification.is_active == True,  # noqa: E712
                    )
                    .order_by(EmployeeQualification.completion_date)
                )
            ).all()
        ]
        training = [
            EmployeeTrainingRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeTrainingRecord, self.actor.organization_id)
                    .where(
                        EmployeeTrainingRecord.employee_id == employee_id,
                        EmployeeTrainingRecord.is_active == True,  # noqa: E712
                    )
                    .order_by(EmployeeTrainingRecord.completion_date.desc())
                )
            ).all()
        ]
        documents = [
            EmployeeDocumentRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeDocument, self.actor.organization_id)
                    .where(
                        EmployeeDocument.employee_id == employee_id,
                        EmployeeDocument.is_active == True,  # noqa: E712
                    )
                    .order_by(EmployeeDocument.expiry_date)
                )
            ).all()
        ]
        soon = datetime.now(UTC) + timedelta(days=90)
        expiring_documents = [
            d
            for d in documents
            if d.expiry_date is not None
            and datetime(d.expiry_date.year, d.expiry_date.month, d.expiry_date.day).replace(
                tzinfo=UTC
            )
            <= soon
        ]
        expiring_licenses = [
            lic
            for lic in licenses
            if lic.expiry_date is not None
            and datetime(lic.expiry_date.year, lic.expiry_date.month, lic.expiry_date.day).replace(
                tzinfo=UTC
            )
            <= soon
        ]
        expiring_training = [
            t
            for t in training
            if t.expiry_date is not None
            and datetime(t.expiry_date.year, t.expiry_date.month, t.expiry_date.day).replace(
                tzinfo=UTC
            )
            <= soon
        ]
        authorizations = [
            EmployeeAssetAuthorizationRead.model_validate(row)
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeAssetAuthorization, self.actor.organization_id)
                    .where(EmployeeAssetAuthorization.employee_id == employee_id)
                    .order_by(EmployeeAssetAuthorization.created_at)
                )
            ).all()
        ]
        compliance = await self.compliance(employee)
        read = EmployeeRead.model_validate(employee)
        read.availability_status = availability
        return EmployeeOverview(
            employee=read,
            department=DepartmentRead.model_validate(department) if department else None,
            position=PositionRead.model_validate(position) if position else None,
            supervisor=EmployeeRead.model_validate(supervisor) if supervisor else None,
            availability_status=availability,
            compliance=compliance,
            current_assignment=current,
            current_project_id=current.project_id if current else None,
            current_project_name=current_project_name,
            current_location_id=current.location_id if current else None,
            current_location_name=current_location_name,
            current_rotation=EmployeeRotationRead.model_validate(current_rotation)
            if current_rotation
            else None,
            primary_emergency_contact=primary_emergency,
            emergency_contacts=emergency_contacts,
            family_summary=FamilySummary(
                spouse=spouse,
                children_count=children,
                dependants_count=dependants,
                next_of_kin=next_of_kin,
                primary_next_of_kin=primary_nok,
            ),
            current_resume=EmployeeResumeRead.model_validate(current_resume)
            if current_resume
            else None,
            skills=skills,
            licenses=licenses,
            qualifications=qualifications,
            recent_training=training[:10],
            expiring_documents=expiring_documents,
            expiring_licenses=expiring_licenses,
            expiring_training=expiring_training,
            recent_assignments=assignments[:10],
            asset_authorizations=authorizations,
        )

    async def _project_name(self, project_id: uuid.UUID) -> str | None:
        project = await self.session.get(Project, project_id)
        if project is None or project.organization_id != self.actor.organization_id:
            return None
        return project.name

    async def _location_name(self, location_id: uuid.UUID) -> str | None:
        location = await self.session.get(Location, location_id)
        if location is None or location.organization_id != self.actor.organization_id:
            return None
        return location.name

    async def _current_rotation(self, employee_id: uuid.UUID) -> EmployeeRotation | None:
        today = date.today()
        rotations = (
            await self.session.scalars(
                organization_query(EmployeeRotation, self.actor.organization_id)
                .where(
                    EmployeeRotation.employee_id == employee_id,
                    EmployeeRotation.status.in_(
                        [
                            RotationStatus.PLANNED,
                            RotationStatus.ON_SITE,
                            RotationStatus.OFF_ROTATION,
                        ]
                    ),
                )
                .order_by(EmployeeRotation.work_start_date.desc())
            )
        ).all()
        for rotation in rotations:
            if rotation.work_start_date <= today <= rotation.off_end_date:
                return rotation
        return rotations[0] if rotations else None

    async def _fill_skill_names(self, skills: Sequence[EmployeeSkillRead]) -> None:
        if not skills:
            return
        ids = {s.skill_id for s in skills}
        rows = (await self.session.scalars(select(Skill).where(Skill.id.in_(ids)))).all()
        names = {row.id: row.name for row in rows}
        for skill in skills:
            skill.skill_name = names.get(skill.skill_id)

    # ---- dashboard ----

    async def dashboard(self) -> WorkforceDashboard:
        org = self.actor.organization_id
        employees = (await self.session.scalars(self._scope())).all()
        avail = await availability_map(self.session, org, list(employees))
        counts = {status: 0 for status in AvailabilityStatus}
        for employee in employees:
            counts[avail.get(employee.id, AvailabilityStatus.UNAVAILABLE)] += 1
        active = sum(
            1 for e in employees if e.is_active and e.employment_status == EmploymentStatus.ACTIVE
        )
        by_department: dict[str, int] = {}
        by_position: dict[str, int] = {}
        for employee in employees:
            dept = employee.department or "Unassigned"
            by_department[dept] = by_department.get(dept, 0) + 1
        positions = (
            (
                await self.session.scalars(
                    organization_query(Position, org).where(
                        Position.id.in_({e.position_id for e in employees if e.position_id})
                    )
                )
            ).all()
            if any(e.position_id for e in employees)
            else []
        )
        position_names = {p.id: p.title for p in positions}
        for employee in employees:
            key = position_names.get(employee.position_id) if employee.position_id else None
            key = key or employee.job_title or "Unspecified"
            by_position[key] = by_position.get(key, 0) + 1
        active_assignments = (
            await self.session.scalars(
                organization_query(EmployeeAssignment, org).where(
                    EmployeeAssignment.status == AssignmentStatus.ACTIVE
                )
            )
        ).all()
        project_ids = {a.project_id for a in active_assignments}
        project_names: dict[uuid.UUID, str] = {}
        if project_ids:
            for project in (
                await self.session.scalars(select(Project).where(Project.id.in_(project_ids)))
            ).all():
                project_names[project.id] = project.name
        by_project: dict[str, int] = {}
        for assignment in active_assignments:
            key = project_names.get(assignment.project_id, "Unknown")
            by_project[key] = by_project.get(key, 0) + 1
        today = date.today()
        warn = today + timedelta(days=EXPIRY_WARNING_DAYS)
        documents = (
            await self.session.scalars(
                organization_query(EmployeeDocument, org).where(
                    EmployeeDocument.is_active == True  # noqa: E712
                )
            )
        ).all()
        expiring_documents = sum(
            1 for d in documents if d.expiry_date and today <= d.expiry_date <= warn
        )
        expired_documents = sum(1 for d in documents if d.expiry_date and d.expiry_date < today)
        licenses = (
            await self.session.scalars(
                organization_query(EmployeeLicense, org).where(
                    EmployeeLicense.is_active == True  # noqa: E712
                )
            )
        ).all()
        expiring_licenses = sum(
            1 for lic in licenses if lic.expiry_date and today <= lic.expiry_date <= warn
        )
        expired_licenses = sum(1 for lic in licenses if lic.expiry_date and lic.expiry_date < today)
        trainings = (
            await self.session.scalars(
                organization_query(EmployeeTrainingRecord, org).where(
                    EmployeeTrainingRecord.is_active == True  # noqa: E712
                )
            )
        ).all()
        expiring_training = sum(
            1 for t in trainings if t.expiry_date and today <= t.expiry_date <= warn
        )
        contract_cutoff = today + timedelta(days=CONTRACT_WARNING_DAYS)
        contracts_expiring = sum(
            1
            for e in employees
            if e.contract_end_date and today <= e.contract_end_date <= contract_cutoff
        )
        contact_employee_ids = {
            row.employee_id
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeEmergencyContact, org).where(
                        EmployeeEmergencyContact.is_active == True  # noqa: E712
                    )
                )
            ).all()
        }
        resume_employee_ids = {
            row.employee_id
            for row in (
                await self.session.scalars(
                    organization_query(EmployeeResume, org).where(
                        EmployeeResume.is_current == True,  # noqa: E712
                        EmployeeResume.is_active == True,  # noqa: E712
                    )
                )
            ).all()
        }
        doc_types_by_employee: dict[uuid.UUID, set[str]] = {}
        for doc in documents:
            doc_types_by_employee.setdefault(doc.employee_id, set()).add(doc.document_type.value)
        active_ids = [e.id for e in employees if e.is_active]
        return WorkforceDashboard(
            total_employees=len(employees),
            active_employees=active,
            assigned_employees=counts[AvailabilityStatus.ASSIGNED],
            available_employees=counts[AvailabilityStatus.AVAILABLE],
            off_rotation=counts[AvailabilityStatus.OFF_ROTATION],
            on_leave=counts[AvailabilityStatus.ON_LEAVE],
            suspended=counts[AvailabilityStatus.SUSPENDED],
            employees_by_department=by_department,
            employees_by_position=by_position,
            employees_by_project=by_project,
            expiring_documents=expiring_documents,
            expired_documents=expired_documents,
            expiring_licenses=expiring_licenses,
            expired_licenses=expired_licenses,
            expiring_training=expiring_training,
            contracts_expiring=contracts_expiring,
            employees_without_emergency_contact=sum(
                1 for eid in active_ids if eid not in contact_employee_ids
            ),
            employees_without_current_resume=sum(
                1 for eid in active_ids if eid not in resume_employee_ids
            ),
            employees_missing_required_documents=sum(
                1
                for eid in active_ids
                if not REQUIRED_EMPLOYMENT_DOCUMENTS <= doc_types_by_employee.get(eid, set())
            ),
        )

    # ---- manpower ----

    async def manpower(self, project_id: uuid.UUID) -> ManpowerSummary:
        project = (
            await self.session.scalars(
                select(Project).where(
                    Project.id == project_id,
                    Project.organization_id == self.actor.organization_id,
                )
            )
        ).one_or_none()
        if project is None:
            raise NotFoundError("Project not found")
        assignments = (
            await self.session.scalars(
                organization_query(EmployeeAssignment, self.actor.organization_id).where(
                    EmployeeAssignment.project_id == project_id,
                    EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        ).all()
        employee_ids = [a.employee_id for a in assignments]
        employees = (
            (
                await self.session.scalars(
                    organization_query(Employee, self.actor.organization_id).where(
                        Employee.id.in_(employee_ids)
                    )
                )
            ).all()
            if employee_ids
            else []
        )
        by_id = {e.id: e for e in employees}
        today = date.today()
        rotations = (
            (
                await self.session.scalars(
                    organization_query(EmployeeRotation, self.actor.organization_id).where(
                        EmployeeRotation.employee_id.in_(employee_ids),
                        EmployeeRotation.status.in_(
                            [RotationStatus.ON_SITE, RotationStatus.OFF_ROTATION]
                        ),
                    )
                )
            ).all()
            if employee_ids
            else []
        )
        rotation_by_employee: dict[uuid.UUID, str] = {}
        on_site = 0
        off_rotation = 0
        for rotation in rotations:
            if rotation.work_start_date <= today <= rotation.work_end_date:
                rotation_by_employee[rotation.employee_id] = "ON_SITE"
                on_site += 1
            elif rotation.off_start_date <= today <= rotation.off_end_date:
                rotation_by_employee.setdefault(rotation.employee_id, "OFF_ROTATION")
                off_rotation += 1
        departments: dict[str, int] = {}
        positions: dict[str, int] = {}
        roles: dict[str, int] = {}
        rotation_groups: dict[str, int] = {}
        for assignment in assignments:
            employee = by_id.get(assignment.employee_id)
            dept = employee.department if employee and employee.department else "Unassigned"
            departments[dept] = departments.get(dept, 0) + 1
            pos = "Unspecified"
            if employee and employee.position_id:
                position = await self.session.get(Position, employee.position_id)
                if position is not None:
                    pos = position.title
            elif employee and employee.job_title:
                pos = employee.job_title
            positions[pos] = positions.get(pos, 0) + 1
            role = assignment.role_on_project or "Unspecified"
            roles[role] = roles.get(role, 0) + 1
            state = rotation_by_employee.get(assignment.employee_id, "NO_ROTATION")
            rotation_groups[state] = rotation_groups.get(state, 0) + 1
        relief_candidates = (
            await self.session.scalars(
                self._scope()
                .where(Employee.is_active == True)  # noqa: E712
                .order_by(Employee.last_name, Employee.first_name)
                .limit(200)
            )
        ).all()
        relief_avail = await availability_map(
            self.session, self.actor.organization_id, list(relief_candidates)
        )
        relief = [
            await self._to_basic(e, relief_avail.get(e.id))
            for e in relief_candidates
            if relief_avail.get(e.id) == AvailabilityStatus.AVAILABLE
            and e.id not in set(employee_ids)
        ][:20]
        return ManpowerSummary(
            project_id=project_id,
            total_assigned=len(assignments),
            on_site=on_site,
            off_rotation=off_rotation,
            by_department=[ManpowerGroup(key=k, count=v) for k, v in sorted(departments.items())],
            by_position=[ManpowerGroup(key=k, count=v) for k, v in sorted(positions.items())],
            by_role=[ManpowerGroup(key=k, count=v) for k, v in sorted(roles.items())],
            by_rotation_status=[
                ManpowerGroup(key=k, count=v) for k, v in sorted(rotation_groups.items())
            ],
            relief_staff=relief,
        )

    # ---- activity ----

    async def activity(self, employee_id: uuid.UUID) -> Sequence[ActivityEntry]:
        await self._get_or_404(employee_id)
        marker = str(employee_id)
        entity_types = [
            "employee",
            "employee_assignment",
            "employee_document",
            "employee_resume",
            "employee_family_member",
            "employee_emergency_contact",
            "employee_qualification",
            "employee_skill",
            "employee_training_record",
            "employee_license",
            "employee_rotation",
            "employee_asset_authorization",
            "time_log",
            "leave_request",
        ]
        direct = organization_query(AuditLog, self.actor.organization_id).where(
            AuditLog.entity_type.in_(entity_types),
            or_(
                AuditLog.entity_id == employee_id,
                AuditLog.new_values["employee_id"].astext == marker,
            ),
        )
        rows = (
            await self.session.scalars(direct.order_by(AuditLog.created_at.desc()).limit(50))
        ).all()
        return [
            ActivityEntry(
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                occurred_at=row.created_at,
                summary=(row.new_values or {}).get("title")
                or (row.new_values or {}).get("full_name")
                or (row.new_values or {}).get("assignment_number"),
            )
            for row in rows
        ]
