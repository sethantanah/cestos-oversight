"""Workforce related-entity services: departments through asset authorizations."""

import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import Request
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.storage import LocalStorage
from app.models import (
    Asset,
    AssetCategory,
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
    Position,
    Project,
    RotationPattern,
    Skill,
    User,
)
from app.models.employee import (
    AuthorizationStatus,
    DocumentType,
    LeaveRequest,
    TimeLog,
    LeaveRequestStatus,
    RotationStatus,
    TrainingStatus,
    VerificationStatus,
    TimeLogStatus,
)
from app.repositories.base import organization_query
from app.schemas.common import Page
from app.schemas.employee import (
    AssetAuthorizationCreate,
    AssetAuthorizationUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DocumentExpiringRead,
    EmergencyContactCreate,
    EmergencyContactUpdate,
    EmployeeAssetAuthorizationRead,
    EmployeeDocumentCreate,
    EmployeeDocumentRead,
    EmployeeDocumentUpdate,
    EmployeeEmergencyContactRead,
    EmployeeFamilyCreate,
    EmployeeFamilyRead,
    EmployeeFamilyUpdate,
    EmployeeLicenseRead,
    EmployeeQualificationRead,
    EmployeeResumeCreate,
    EmployeeResumeRead,
    EmployeeRotationCreate,
    EmployeeRotationRead,
    EmployeeSkillCreate,
    EmployeeSkillRead,
    EmployeeSkillUpdate,
    EmployeeTrainingRead,
    LicenseCreate,
    LicenseExpiringRead,
    LicenseUpdate,
    PositionCreate,
    PositionRead,
    PositionUpdate,
    QualificationCreate,
    QualificationUpdate,
    RotationPatternCreate,
    RotationPatternRead,
    RotationPatternUpdate,
    SkillCreate,
    SkillRead,
    SkillUpdate,
    TrainingCreate,
    TrainingExpiringRead,
    TrainingUpdate,
    TimeLogCreate,
    TimeLogRead,
    LeaveRequestCreate,
    LeaveRequestUpdate,
    LeaveRequestRead,
)
from app.services.audit import RequestMetadata, record_audit, request_metadata


def _meta(request: Request | None) -> RequestMetadata:
    if request is None:
        return {"ip_address": None, "user_agent": None}
    return request_metadata(request)


async def _employee_or_404(session: AsyncSession, actor: User, employee_id: uuid.UUID) -> Employee:
    employee = (
        await session.scalars(
            organization_query(Employee, actor.organization_id).where(Employee.id == employee_id)
        )
    ).one_or_none()
    if employee is None:
        raise NotFoundError("Employee not found")
    return employee


def _page[T](items: list[T], total: int, page: int, page_size: int) -> Page[T]:
    return Page(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if page_size else 0,
    )


class DepartmentService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def _scope(self) -> Select[tuple[Department]]:
        return organization_query(Department, self.actor.organization_id)

    async def list(self) -> Sequence[DepartmentRead]:
        rows = (await self.session.scalars(self._scope().order_by(Department.name))).all()
        return [DepartmentRead.model_validate(row) for row in rows]

    async def create(self, body: DepartmentCreate) -> DepartmentRead:
        try:
            await self._check_refs(body.manager_employee_id, body.parent_department_id, None)
            department = Department(
                organization_id=self.actor.organization_id,
                name=body.name,
                code=body.code,
                description=body.description,
                manager_employee_id=body.manager_employee_id,
                parent_department_id=body.parent_department_id,
            )
            self.session.add(department)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="department.created",
                entity_type="department",
                entity_id=department.id,
                new_values={"name": body.name},
            )
            await self.session.commit()
            return DepartmentRead.model_validate(department)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(self, department_id: uuid.UUID, body: DepartmentUpdate) -> DepartmentRead:
        try:
            department = (
                await self.session.scalars(self._scope().where(Department.id == department_id))
            ).one_or_none()
            if department is None:
                raise NotFoundError("Department not found")
            data = body.model_dump(exclude_unset=True)
            await self._check_refs(
                data.get("manager_employee_id", department.manager_employee_id),
                data.get("parent_department_id", department.parent_department_id),
                department_id,
            )
            for key, value in data.items():
                setattr(department, key, value)
            department.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="department.updated",
                entity_type="department",
                entity_id=department.id,
                new_values={"name": department.name},
            )
            await self.session.commit()
            return DepartmentRead.model_validate(department)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _check_refs(
        self,
        manager_id: uuid.UUID | None,
        parent_id: uuid.UUID | None,
        self_id: uuid.UUID | None,
    ) -> None:
        if manager_id is not None:
            manager = (
                await self.session.scalars(
                    organization_query(Employee, self.actor.organization_id).where(
                        Employee.id == manager_id
                    )
                )
            ).one_or_none()
            if manager is None:
                raise NotFoundError("Manager employee not found")
        if parent_id is not None:
            if parent_id == self_id:
                raise ValidationError("A department cannot be its own parent")
            parent = (
                await self.session.scalars(self._scope().where(Department.id == parent_id))
            ).one_or_none()
            if parent is None:
                raise NotFoundError("Parent department not found")


class PositionService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def _scope(self) -> Select[tuple[Position]]:
        return organization_query(Position, self.actor.organization_id)

    async def list(self) -> Sequence[PositionRead]:
        rows = (await self.session.scalars(self._scope().order_by(Position.title))).all()
        return [PositionRead.model_validate(row) for row in rows]

    async def create(self, body: PositionCreate) -> PositionRead:
        try:
            if body.department_id is not None:
                await self._department_or_404(body.department_id)
            position = Position(
                organization_id=self.actor.organization_id,
                title=body.title,
                code=body.code,
                department_id=body.department_id,
                description=body.description,
                grade=body.grade,
                level=body.level,
                is_field_role=body.is_field_role,
            )
            self.session.add(position)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="position.created",
                entity_type="position",
                entity_id=position.id,
                new_values={"title": body.title},
            )
            await self.session.commit()
            return PositionRead.model_validate(position)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(self, position_id: uuid.UUID, body: PositionUpdate) -> PositionRead:
        try:
            position = (
                await self.session.scalars(self._scope().where(Position.id == position_id))
            ).one_or_none()
            if position is None:
                raise NotFoundError("Position not found")
            data = body.model_dump(exclude_unset=True)
            if data.get("department_id") is not None:
                await self._department_or_404(data["department_id"])
            for key, value in data.items():
                setattr(position, key, value)
            position.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="position.updated",
                entity_type="position",
                entity_id=position.id,
                new_values={"title": position.title},
            )
            await self.session.commit()
            return PositionRead.model_validate(position)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _department_or_404(self, department_id: uuid.UUID) -> None:
        found = (
            await self.session.scalars(
                organization_query(Department, self.actor.organization_id).where(
                    Department.id == department_id
                )
            )
        ).one_or_none()
        if found is None:
            raise NotFoundError("Department not found")


class FamilyService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeFamilyRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeFamilyMember, self.actor.organization_id)
                .where(EmployeeFamilyMember.employee_id == employee_id)
                .order_by(EmployeeFamilyMember.full_name)
            )
        ).all()
        return [EmployeeFamilyRead.model_validate(row) for row in rows]

    async def get(self, member_id: uuid.UUID) -> EmployeeFamilyRead:
        member = await self._get_or_404(member_id)
        return EmployeeFamilyRead.model_validate(member)

    async def _get_or_404(self, member_id: uuid.UUID) -> EmployeeFamilyMember:
        member = (
            await self.session.scalars(
                organization_query(EmployeeFamilyMember, self.actor.organization_id).where(
                    EmployeeFamilyMember.id == member_id
                )
            )
        ).one_or_none()
        if member is None:
            raise NotFoundError("Family member not found")
        return member

    async def create(
        self, employee_id: uuid.UUID, body: EmployeeFamilyCreate, request: Request | None = None
    ) -> EmployeeFamilyRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            if (
                body.dependency_end_date
                and body.dependency_start_date
                and (body.dependency_end_date < body.dependency_start_date)
            ):
                raise ValidationError("Dependency end cannot precede start")
            member = EmployeeFamilyMember(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                full_name=body.full_name,
                relationship_type=body.relationship_type,
                date_of_birth=body.date_of_birth,
                gender=body.gender,
                phone=body.phone,
                email=str(body.email).lower() if body.email else None,
                address=body.address,
                occupation=body.occupation,
                employer=body.employer,
                is_dependent=body.is_dependent,
                is_next_of_kin=body.is_next_of_kin,
                is_primary_next_of_kin=body.is_primary_next_of_kin,
                is_emergency_contact=body.is_emergency_contact,
                dependency_start_date=body.dependency_start_date,
                dependency_end_date=body.dependency_end_date,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(member)
            await self.session.flush()
            if body.is_primary_next_of_kin:
                await self._exclusive_flag(member, "is_primary_next_of_kin")
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.family_member_added",
                entity_type="employee_family_member",
                entity_id=member.id,
                new_values={"employee_id": str(employee_id), "full_name": body.full_name},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeFamilyRead.model_validate(member)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, member_id: uuid.UUID, body: EmployeeFamilyUpdate, request: Request | None = None
    ) -> EmployeeFamilyRead:
        try:
            member = await self._get_or_404(member_id)
            data = body.model_dump(exclude_unset=True)
            if "email" in data and data["email"] is not None:
                data["email"] = str(data["email"]).lower()
            start = data.get("dependency_start_date", member.dependency_start_date)
            end = data.get("dependency_end_date", member.dependency_end_date)
            if start and end and end < start:
                raise ValidationError("Dependency end cannot precede start")
            for key, value in data.items():
                setattr(member, key, value)
            member.updated_by_id = self.actor.id
            member.updated_at = datetime.now(UTC)
            await self.session.flush()
            if data.get("is_primary_next_of_kin"):
                await self._exclusive_flag(member, "is_primary_next_of_kin")
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.family_member_updated",
                entity_type="employee_family_member",
                entity_id=member.id,
                new_values={"full_name": member.full_name},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeFamilyRead.model_validate(member)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def archive(
        self, member_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeFamilyRead:
        try:
            member = await self._get_or_404(member_id)
            if member.archived_at is not None or not member.is_active:
                raise ConflictError("Family member is already archived")
            member.is_active = False
            member.archived_at = datetime.now(UTC)
            member.updated_by_id = self.actor.id
            member.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.family_member_archived",
                entity_type="employee_family_member",
                entity_id=member.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeFamilyRead.model_validate(member)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def set_dependent(
        self, member_id: uuid.UUID, value: bool, request: Request | None = None
    ) -> EmployeeFamilyRead:
        return await self.update(
            member_id,
            EmployeeFamilyUpdate(is_dependent=value),
            request,
        )

    async def set_next_of_kin(
        self, member_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeFamilyRead:
        try:
            member = await self._get_or_404(member_id)
            member.is_next_of_kin = True
            member.updated_by_id = self.actor.id
            member.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.family_member_updated",
                entity_type="employee_family_member",
                entity_id=member.id,
                new_values={"is_next_of_kin": True},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeFamilyRead.model_validate(member)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _exclusive_flag(self, member: EmployeeFamilyMember, field: str) -> None:
        others = (
            await self.session.scalars(
                organization_query(EmployeeFamilyMember, self.actor.organization_id).where(
                    EmployeeFamilyMember.employee_id == member.employee_id,
                    EmployeeFamilyMember.id != member.id,
                )
            )
        ).all()
        for other in others:
            setattr(other, field, False)
        await self.session.flush()


class EmergencyContactService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeEmergencyContactRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeEmergencyContact, self.actor.organization_id)
                .where(EmployeeEmergencyContact.employee_id == employee_id)
                .order_by(
                    EmployeeEmergencyContact.is_primary.desc(),
                    EmployeeEmergencyContact.priority,
                )
            )
        ).all()
        return [EmployeeEmergencyContactRead.model_validate(row) for row in rows]

    async def primary(self, employee_id: uuid.UUID) -> EmployeeEmergencyContactRead:
        contacts = await self.list(employee_id)
        for contact in contacts:
            if contact.is_primary:
                return contact
        if contacts:
            return contacts[0]
        raise NotFoundError("No emergency contact found")

    async def get(self, contact_id: uuid.UUID) -> EmployeeEmergencyContactRead:
        return EmployeeEmergencyContactRead.model_validate(await self._get_or_404(contact_id))

    async def _get_or_404(self, contact_id: uuid.UUID) -> EmployeeEmergencyContact:
        contact = (
            await self.session.scalars(
                organization_query(EmployeeEmergencyContact, self.actor.organization_id).where(
                    EmployeeEmergencyContact.id == contact_id
                )
            )
        ).one_or_none()
        if contact is None:
            raise NotFoundError("Emergency contact not found")
        return contact

    async def create(
        self, employee_id: uuid.UUID, body: EmergencyContactCreate, request: Request | None = None
    ) -> EmployeeEmergencyContactRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            if body.family_member_id is not None:
                await self._family_or_404(body.family_member_id, employee_id)
            contact = EmployeeEmergencyContact(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                family_member_id=body.family_member_id,
                full_name=body.full_name,
                relationship=body.relationship,
                primary_phone=body.primary_phone,
                secondary_phone=body.secondary_phone,
                email=str(body.email).lower() if body.email else None,
                address=body.address,
                priority=body.priority,
                is_primary=body.is_primary,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(contact)
            await self.session.flush()
            if body.is_primary:
                await self._exclusive_primary(contact)
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.emergency_contact_added",
                entity_type="employee_emergency_contact",
                entity_id=contact.id,
                new_values={"employee_id": str(employee_id), "full_name": body.full_name},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeEmergencyContactRead.model_validate(contact)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, contact_id: uuid.UUID, body: EmergencyContactUpdate, request: Request | None = None
    ) -> EmployeeEmergencyContactRead:
        try:
            contact = await self._get_or_404(contact_id)
            data = body.model_dump(exclude_unset=True)
            if data.get("family_member_id") is not None:
                await self._family_or_404(data["family_member_id"], contact.employee_id)
            if "email" in data and data["email"] is not None:
                data["email"] = str(data["email"]).lower()
            for key, value in data.items():
                setattr(contact, key, value)
            contact.updated_by_id = self.actor.id
            contact.updated_at = datetime.now(UTC)
            await self.session.flush()
            if data.get("is_primary"):
                await self._exclusive_primary(contact)
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.emergency_contact_updated",
                entity_type="employee_emergency_contact",
                entity_id=contact.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeEmergencyContactRead.model_validate(contact)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def set_primary(
        self, contact_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeEmergencyContactRead:
        try:
            contact = await self._get_or_404(contact_id)
            contact.is_primary = True
            contact.updated_by_id = self.actor.id
            contact.updated_at = datetime.now(UTC)
            await self.session.flush()
            await self._exclusive_primary(contact)
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.emergency_contact_primary_changed",
                entity_type="employee_emergency_contact",
                entity_id=contact.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeEmergencyContactRead.model_validate(contact)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def archive(
        self, contact_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeEmergencyContactRead:
        try:
            contact = await self._get_or_404(contact_id)
            if contact.archived_at is not None or not contact.is_active:
                raise ConflictError("Emergency contact is already archived")
            contact.is_active = False
            contact.archived_at = datetime.now(UTC)
            contact.is_primary = False
            contact.updated_by_id = self.actor.id
            contact.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.emergency_contact_updated",
                entity_type="employee_emergency_contact",
                entity_id=contact.id,
                new_values={"archived": True},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeEmergencyContactRead.model_validate(contact)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _family_or_404(self, member_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        member = (
            await self.session.scalars(
                organization_query(EmployeeFamilyMember, self.actor.organization_id).where(
                    EmployeeFamilyMember.id == member_id
                )
            )
        ).one_or_none()
        if member is None:
            raise NotFoundError("Family member not found")
        if member.employee_id != employee_id:
            raise ValidationError("Family member belongs to a different employee")

    async def _exclusive_primary(self, contact: EmployeeEmergencyContact) -> None:
        others = (
            await self.session.scalars(
                organization_query(EmployeeEmergencyContact, self.actor.organization_id).where(
                    EmployeeEmergencyContact.employee_id == contact.employee_id,
                    EmployeeEmergencyContact.id != contact.id,
                    EmployeeEmergencyContact.is_primary == True,  # noqa: E712
                )
            )
        ).all()
        for other in others:
            other.is_primary = False
        await self.session.flush()


class ResumeService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeResumeRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeResume, self.actor.organization_id)
                .where(EmployeeResume.employee_id == employee_id)
                .order_by(EmployeeResume.version.desc())
            )
        ).all()
        return [EmployeeResumeRead.model_validate(row) for row in rows]

    async def current(self, employee_id: uuid.UUID) -> EmployeeResumeRead:
        await _employee_or_404(self.session, self.actor, employee_id)
        resume = (
            await self.session.scalars(
                organization_query(EmployeeResume, self.actor.organization_id).where(
                    EmployeeResume.employee_id == employee_id,
                    EmployeeResume.is_current == True,  # noqa: E712
                    EmployeeResume.is_active == True,  # noqa: E712
                )
            )
        ).first()
        if resume is None:
            raise NotFoundError("No current resume found")
        return EmployeeResumeRead.model_validate(resume)

    async def add(
        self,
        employee_id: uuid.UUID,
        body: EmployeeResumeCreate,
        storage: LocalStorage | None,
        data: bytes | None,
        filename: str | None,
        content_type: str | None,
        request: Request | None = None,
    ) -> EmployeeResumeRead:
        """Add a resume version; metadata-only when data is None, upload otherwise."""
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            storage_path: str | None = None
            file_name = body.file_name
            mime_type = body.mime_type
            file_size = body.file_size
            file_url = str(body.file_url)
            if data is not None:
                if storage is None:
                    raise ValidationError("File storage is not configured")
                try:
                    stored = await run_in_threadpool(
                        storage.save,
                        f"employee-resumes/{employee_id}",
                        data,
                        filename or "resume.pdf",
                        content_type,
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                storage_path = stored.relative_path
                file_name = stored.filename
                mime_type = stored.mime_type
                file_size = stored.size_bytes
            latest = (
                await self.session.scalars(
                    organization_query(EmployeeResume, self.actor.organization_id)
                    .where(EmployeeResume.employee_id == employee_id)
                    .order_by(EmployeeResume.version.desc())
                    .limit(1)
                )
            ).first()
            version = (latest.version + 1) if latest else 1
            resume = EmployeeResume(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                title=body.title,
                file_url="pending" if data is not None else file_url,
                storage_path=storage_path,
                file_name=file_name,
                mime_type=mime_type,
                file_size=file_size,
                version=version,
                is_current=True,
                uploaded_at=datetime.now(UTC),
                uploaded_by_id=self.actor.id,
                notes=body.notes,
            )
            self.session.add(resume)
            await self.session.flush()
            if data is not None:
                resume.file_url = f"/api/v1/employees/{employee_id}/resumes/{resume.id}/download"
                resume.updated_at = datetime.now(UTC)
                await self.session.flush()
            await self._only_current(resume)
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.resume_uploaded",
                entity_type="employee_resume",
                entity_id=resume.id,
                new_values={"employee_id": str(employee_id), "version": version},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeResumeRead.model_validate(resume)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, resume_id: uuid.UUID, title: str | None, notes: str | None
    ) -> EmployeeResumeRead:
        try:
            resume = await self._get_or_404(resume_id)
            if title is not None:
                resume.title = title
            if notes is not None:
                resume.notes = notes
            resume.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.resume_uploaded",
                entity_type="employee_resume",
                entity_id=resume.id,
                new_values={"title": resume.title},
            )
            await self.session.commit()
            return EmployeeResumeRead.model_validate(resume)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def set_current(
        self, resume_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeResumeRead:
        try:
            resume = await self._get_or_404(resume_id)
            if not resume.is_active or resume.archived_at is not None:
                raise ConflictError("Cannot mark an archived resume current")
            resume.is_current = True
            resume.updated_at = datetime.now(UTC)
            await self.session.flush()
            await self._only_current(resume)
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.resume_current_changed",
                entity_type="employee_resume",
                entity_id=resume.id,
                new_values={"version": resume.version},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeResumeRead.model_validate(resume)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def archive(
        self, resume_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeResumeRead:
        try:
            resume = await self._get_or_404(resume_id)
            if resume.archived_at is not None or not resume.is_active:
                raise ConflictError("Resume is already archived")
            resume.is_active = False
            resume.is_current = False
            resume.archived_at = datetime.now(UTC)
            resume.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.resume_current_changed",
                entity_type="employee_resume",
                entity_id=resume.id,
                new_values={"archived": True},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeResumeRead.model_validate(resume)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def download(
        self, employee_id: uuid.UUID, resume_id: uuid.UUID, storage: LocalStorage
    ) -> tuple[Path, str, str]:
        resume = await self._get_or_404(resume_id)
        if resume.employee_id != employee_id:
            raise NotFoundError("Resume not found")
        if not resume.storage_path:
            raise NotFoundError("No stored file for this resume")
        try:
            path = await run_in_threadpool(storage.resolve, resume.storage_path)
            exists = await run_in_threadpool(path.is_file)
        except ValueError:
            raise NotFoundError("Stored file is unavailable") from None
        if not exists:
            raise NotFoundError("Stored file is missing")
        return (
            path,
            resume.mime_type or "application/octet-stream",
            resume.file_name or resume.title,
        )

    async def _get_or_404(self, resume_id: uuid.UUID) -> EmployeeResume:
        resume = (
            await self.session.scalars(
                organization_query(EmployeeResume, self.actor.organization_id).where(
                    EmployeeResume.id == resume_id
                )
            )
        ).one_or_none()
        if resume is None:
            raise NotFoundError("Resume not found")
        return resume

    async def _only_current(self, resume: EmployeeResume) -> None:
        others = (
            await self.session.scalars(
                organization_query(EmployeeResume, self.actor.organization_id).where(
                    EmployeeResume.employee_id == resume.employee_id,
                    EmployeeResume.id != resume.id,
                    EmployeeResume.is_current == True,  # noqa: E712
                )
            )
        ).all()
        for other in others:
            other.is_current = False
        await self.session.flush()


class DocumentService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeDocumentRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeDocument, self.actor.organization_id)
                .where(EmployeeDocument.employee_id == employee_id)
                .order_by(EmployeeDocument.created_at)
            )
        ).all()
        return [EmployeeDocumentRead.model_validate(row) for row in rows]

    async def get(self, document_id: uuid.UUID) -> EmployeeDocumentRead:
        return EmployeeDocumentRead.model_validate(await self._get_or_404(document_id))

    async def _get_or_404(self, document_id: uuid.UUID) -> EmployeeDocument:
        document = (
            await self.session.scalars(
                organization_query(EmployeeDocument, self.actor.organization_id).where(
                    EmployeeDocument.id == document_id
                )
            )
        ).one_or_none()
        if document is None:
            raise NotFoundError("Document not found")
        return document

    async def add(
        self,
        employee_id: uuid.UUID,
        body: EmployeeDocumentCreate,
        request: Request | None = None,
    ) -> EmployeeDocumentRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            self._check_dates(body.issue_date, body.expiry_date)
            document = EmployeeDocument(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                document_type=body.document_type,
                title=body.title,
                document_number=body.document_number,
                file_url=str(body.file_url),
                file_name=body.file_name,
                mime_type=body.mime_type,
                file_size=body.file_size,
                issue_date=body.issue_date,
                expiry_date=body.expiry_date,
                issuing_authority=body.issuing_authority,
                issuing_country=body.issuing_country,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(document)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.document_added",
                entity_type="employee_document",
                entity_id=document.id,
                new_values={"employee_id": str(employee_id), "title": body.title},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self,
        document_id: uuid.UUID,
        body: EmployeeDocumentUpdate,
        request: Request | None = None,
    ) -> EmployeeDocumentRead:
        try:
            document = await self._get_or_404(document_id)
            data = body.model_dump(exclude_unset=True)
            issue = data.get("issue_date", document.issue_date)
            expiry = data.get("expiry_date", document.expiry_date)
            self._check_dates(issue, expiry)
            for key, value in data.items():
                setattr(document, key, value)
            if (
                document.expiry_date
                and document.expiry_date < date.today()
                and document.verification_status == VerificationStatus.VERIFIED
            ):
                document.verification_status = VerificationStatus.EXPIRED
            document.updated_by_id = self.actor.id
            document.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.document_updated",
                entity_type="employee_document",
                entity_id=document.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def verify(
        self, document_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeDocumentRead:
        try:
            document = await self._get_or_404(document_id)
            if document.expiry_date and document.expiry_date < date.today():
                raise ConflictError("Cannot verify an expired document")
            document.verification_status = VerificationStatus.VERIFIED
            document.verified_by_id = self.actor.id
            document.verified_at = datetime.now(UTC)
            document.updated_by_id = self.actor.id
            document.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.document_verified",
                entity_type="employee_document",
                entity_id=document.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def reject(
        self, document_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeDocumentRead:
        try:
            document = await self._get_or_404(document_id)
            document.verification_status = VerificationStatus.REJECTED
            document.verified_by_id = self.actor.id
            document.verified_at = datetime.now(UTC)
            document.updated_by_id = self.actor.id
            document.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.document_rejected",
                entity_type="employee_document",
                entity_id=document.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def archive(
        self, document_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeDocumentRead:
        try:
            document = await self._get_or_404(document_id)
            if document.archived_at is not None or not document.is_active:
                raise ConflictError("Document is already archived")
            document.is_active = False
            document.archived_at = datetime.now(UTC)
            document.updated_by_id = self.actor.id
            document.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.document_updated",
                entity_type="employee_document",
                entity_id=document.id,
                new_values={"archived": True},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def upload(
        self,
        employee_id: uuid.UUID,
        data: bytes,
        filename: str | None,
        content_type: str | None,
        storage: LocalStorage,
        document_type: DocumentType = DocumentType.OTHER,
        title: str | None = None,
        document_number: str | None = None,
        issue_date: date | None = None,
        expiry_date: date | None = None,
        issuing_authority: str | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ) -> EmployeeDocumentRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            self._check_dates(issue_date, expiry_date)
            resolved_title = title or (filename or "Untitled document")
            if len(resolved_title) > 200:
                raise ValidationError("Document title must be at most 200 characters")
            try:
                stored = await run_in_threadpool(
                    storage.save,
                    f"employee-documents/{employee_id}",
                    data,
                    filename or "upload.bin",
                    content_type,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            document = EmployeeDocument(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                document_type=document_type,
                title=resolved_title,
                document_number=document_number,
                file_url="pending",
                storage_path=stored.relative_path,
                file_name=stored.filename,
                mime_type=stored.mime_type,
                file_size=stored.size_bytes,
                issue_date=issue_date,
                expiry_date=expiry_date,
                issuing_authority=issuing_authority,
                notes=notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(document)
            await self.session.flush()
            document.file_url = f"/api/v1/employees/{employee_id}/documents/{document.id}/download"
            document.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.document_added",
                entity_type="employee_document",
                entity_id=document.id,
                new_values={
                    "employee_id": str(employee_id),
                    "title": resolved_title,
                    "file_name": stored.filename,
                    "size_bytes": stored.size_bytes,
                },
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeDocumentRead.model_validate(document)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def download(
        self, employee_id: uuid.UUID, document_id: uuid.UUID, storage: LocalStorage
    ) -> tuple[Path, str, str]:
        document = await self._get_or_404(document_id)
        if document.employee_id != employee_id:
            raise NotFoundError("Document not found")
        if not document.storage_path:
            raise NotFoundError("No stored file for this document")
        try:
            path = await run_in_threadpool(storage.resolve, document.storage_path)
            exists = await run_in_threadpool(path.is_file)
        except ValueError:
            raise NotFoundError("Stored file is unavailable") from None
        if not exists:
            raise NotFoundError("Stored file is missing")
        return (
            path,
            document.mime_type or "application/octet-stream",
            document.file_name or document.title,
        )

    async def expiring(self, days: int) -> Sequence[DocumentExpiringRead]:
        cutoff = date.today() + timedelta(days=days)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeDocument, self.actor.organization_id)
                .where(
                    EmployeeDocument.expiry_date.is_not(None),
                    EmployeeDocument.expiry_date <= cutoff,
                    EmployeeDocument.is_active == True,  # noqa: E712
                )
                .order_by(EmployeeDocument.expiry_date)
            )
        ).all()
        employee_ids = {row.employee_id for row in rows}
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
        result = []
        for row in rows:
            employee = by_id.get(row.employee_id)
            if employee is None or row.expiry_date is None:
                continue
            result.append(
                DocumentExpiringRead(
                    document=EmployeeDocumentRead.model_validate(row),
                    employee_number=employee.employee_number,
                    employee_name=f"{employee.first_name} {employee.last_name}",
                    days_until_expiry=(row.expiry_date - today).days,
                )
            )
        return result

    def _check_dates(self, issue: date | None, expiry: date | None) -> None:
        if issue and expiry and expiry < issue:
            raise ValidationError("Document expiry cannot precede issue date")


class QualificationService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeQualificationRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeQualification, self.actor.organization_id)
                .where(EmployeeQualification.employee_id == employee_id)
                .order_by(EmployeeQualification.completion_date)
            )
        ).all()
        return [EmployeeQualificationRead.model_validate(row) for row in rows]

    async def create(
        self, employee_id: uuid.UUID, body: QualificationCreate, request: Request | None = None
    ) -> EmployeeQualificationRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            if body.completion_date and body.start_date and body.completion_date < body.start_date:
                raise ValidationError("Completion cannot precede start")
            if body.document_id is not None:
                await self._document_or_404(body.document_id, employee_id)
            record = EmployeeQualification(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                qualification_type=body.qualification_type,
                qualification_name=body.qualification_name,
                institution=body.institution,
                field_of_study=body.field_of_study,
                start_date=body.start_date,
                completion_date=body.completion_date,
                grade_or_classification=body.grade_or_classification,
                certificate_number=body.certificate_number,
                document_id=body.document_id,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(record)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.qualification_added",
                entity_type="employee_qualification",
                entity_id=record.id,
                new_values={"employee_id": str(employee_id)},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeQualificationRead.model_validate(record)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, qualification_id: uuid.UUID, body: QualificationUpdate, request: Request | None = None
    ) -> EmployeeQualificationRead:
        try:
            record = (
                await self.session.scalars(
                    organization_query(EmployeeQualification, self.actor.organization_id).where(
                        EmployeeQualification.id == qualification_id
                    )
                )
            ).one_or_none()
            if record is None:
                raise NotFoundError("Qualification not found")
            data = body.model_dump(exclude_unset=True)
            start = data.get("start_date", record.start_date)
            completion = data.get("completion_date", record.completion_date)
            if start and completion and completion < start:
                raise ValidationError("Completion cannot precede start")
            if data.get("document_id") is not None:
                await self._document_or_404(data["document_id"], record.employee_id)
            for key, value in data.items():
                setattr(record, key, value)
            record.updated_by_id = self.actor.id
            record.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.qualification_added",
                entity_type="employee_qualification",
                entity_id=record.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeQualificationRead.model_validate(record)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def archive(
        self, qualification_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeQualificationRead:
        try:
            record = (
                await self.session.scalars(
                    organization_query(EmployeeQualification, self.actor.organization_id).where(
                        EmployeeQualification.id == qualification_id
                    )
                )
            ).one_or_none()
            if record is None:
                raise NotFoundError("Qualification not found")
            if record.archived_at is not None or not record.is_active:
                raise ConflictError("Qualification is already archived")
            record.is_active = False
            record.archived_at = datetime.now(UTC)
            record.updated_by_id = self.actor.id
            record.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.qualification_added",
                entity_type="employee_qualification",
                entity_id=record.id,
                new_values={"archived": True},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeQualificationRead.model_validate(record)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _document_or_404(self, document_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        document = (
            await self.session.scalars(
                organization_query(EmployeeDocument, self.actor.organization_id).where(
                    EmployeeDocument.id == document_id
                )
            )
        ).one_or_none()
        if document is None:
            raise NotFoundError("Document not found")
        if document.employee_id != employee_id:
            raise ValidationError("Document belongs to a different employee")


class SkillService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list_all(self) -> Sequence[SkillRead]:
        rows = (
            await self.session.scalars(
                select(Skill)
                .where(
                    or_(
                        Skill.organization_id == self.actor.organization_id,
                        Skill.organization_id.is_(None),
                    )
                )
                .order_by(Skill.name)
            )
        ).all()
        return [SkillRead.model_validate(row) for row in rows]

    async def create(self, body: SkillCreate) -> SkillRead:
        try:
            org_id = body.organization_id
            if org_id is not None and org_id != self.actor.organization_id:
                raise ValidationError("Skill organization must match your organization")
            skill = Skill(
                organization_id=self.actor.organization_id,
                name=body.name,
                category=body.category,
                description=body.description,
            )
            self.session.add(skill)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="skill.created",
                entity_type="skill",
                entity_id=skill.id,
                new_values={"name": body.name},
            )
            await self.session.commit()
            return SkillRead.model_validate(skill)
        except (ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(self, skill_id: uuid.UUID, body: SkillUpdate) -> SkillRead:
        try:
            skill = (
                await self.session.scalars(
                    select(Skill).where(
                        Skill.id == skill_id,
                        or_(
                            Skill.organization_id == self.actor.organization_id,
                            Skill.organization_id.is_(None),
                        ),
                    )
                )
            ).one_or_none()
            if skill is None:
                raise NotFoundError("Skill not found")
            for key, value in body.model_dump(exclude_unset=True).items():
                setattr(skill, key, value)
            skill.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="skill.updated",
                entity_type="skill",
                entity_id=skill.id,
            )
            await self.session.commit()
            return SkillRead.model_validate(skill)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def list_for_employee(self, employee_id: uuid.UUID) -> Sequence[EmployeeSkillRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeSkill, self.actor.organization_id)
                .where(EmployeeSkill.employee_id == employee_id)
                .order_by(EmployeeSkill.created_at)
            )
        ).all()
        reads = [EmployeeSkillRead.model_validate(row) for row in rows]
        await self._fill_names(reads)
        return reads

    async def assign(self, employee_id: uuid.UUID, body: EmployeeSkillCreate) -> EmployeeSkillRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            skill = (
                await self.session.scalars(
                    select(Skill).where(
                        Skill.id == body.skill_id,
                        or_(
                            Skill.organization_id == self.actor.organization_id,
                            Skill.organization_id.is_(None),
                        ),
                    )
                )
            ).one_or_none()
            if skill is None:
                raise NotFoundError("Skill not found")
            existing = (
                await self.session.scalars(
                    organization_query(EmployeeSkill, self.actor.organization_id).where(
                        EmployeeSkill.employee_id == employee_id,
                        EmployeeSkill.skill_id == body.skill_id,
                    )
                )
            ).one_or_none()
            if existing is not None:
                raise ConflictError("Skill is already assigned to this employee")
            link = EmployeeSkill(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                skill_id=body.skill_id,
                proficiency_level=body.proficiency_level,
                years_experience=body.years_experience,
                certification_number=body.certification_number,
                certification_date=body.certification_date,
                expiry_date=body.expiry_date,
                notes=body.notes,
            )
            self.session.add(link)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.skill_added",
                entity_type="employee_skill",
                entity_id=link.id,
                new_values={"employee_id": str(employee_id), "skill_id": str(body.skill_id)},
            )
            await self.session.commit()
            read = EmployeeSkillRead.model_validate(link)
            read.skill_name = skill.name
            return read
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update_link(self, link_id: uuid.UUID, body: EmployeeSkillUpdate) -> EmployeeSkillRead:
        try:
            link = (
                await self.session.scalars(
                    organization_query(EmployeeSkill, self.actor.organization_id).where(
                        EmployeeSkill.id == link_id
                    )
                )
            ).one_or_none()
            if link is None:
                raise NotFoundError("Employee skill not found")
            for key, value in body.model_dump(exclude_unset=True).items():
                setattr(link, key, value)
            link.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.skill_updated",
                entity_type="employee_skill",
                entity_id=link.id,
            )
            await self.session.commit()
            reads = [EmployeeSkillRead.model_validate(link)]
            await self._fill_names(reads)
            return reads[0]
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def unlink(self, link_id: uuid.UUID) -> None:
        try:
            link = (
                await self.session.scalars(
                    organization_query(EmployeeSkill, self.actor.organization_id).where(
                        EmployeeSkill.id == link_id
                    )
                )
            ).one_or_none()
            if link is None:
                raise NotFoundError("Employee skill not found")
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.skill_updated",
                entity_type="employee_skill",
                entity_id=link.id,
                new_values={"removed": True},
            )
            await self.session.delete(link)
            await self.session.commit()
        except NotFoundError:
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _fill_names(self, reads: list[EmployeeSkillRead]) -> None:
        if not reads:
            return
        rows = (
            await self.session.scalars(
                select(Skill).where(Skill.id.in_({r.skill_id for r in reads}))
            )
        ).all()
        names = {row.id: row.name for row in rows}
        for read in reads:
            read.skill_name = names.get(read.skill_id)


class TrainingService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeTrainingRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeTrainingRecord, self.actor.organization_id)
                .where(EmployeeTrainingRecord.employee_id == employee_id)
                .order_by(EmployeeTrainingRecord.completion_date.desc())
            )
        ).all()
        return [EmployeeTrainingRead.model_validate(row) for row in rows]

    async def create(
        self, employee_id: uuid.UUID, body: TrainingCreate, request: Request | None = None
    ) -> EmployeeTrainingRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            if body.completion_date and body.start_date and body.completion_date < body.start_date:
                raise ValidationError("Training completion cannot precede start")
            if body.document_id is not None:
                await self._document_or_404(body.document_id, employee_id)
            record = EmployeeTrainingRecord(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                training_name=body.training_name,
                training_type=body.training_type,
                provider=body.provider,
                start_date=body.start_date,
                completion_date=body.completion_date,
                status=body.status,
                certificate_number=body.certificate_number,
                expiry_date=body.expiry_date,
                score=body.score,
                document_id=body.document_id,
                notes=body.notes,
                created_by_id=self.actor.id,
            )
            self.session.add(record)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.training_added",
                entity_type="employee_training_record",
                entity_id=record.id,
                new_values={"employee_id": str(employee_id), "training_name": body.training_name},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeTrainingRead.model_validate(record)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, training_id: uuid.UUID, body: TrainingUpdate, request: Request | None = None
    ) -> EmployeeTrainingRead:
        try:
            record = (
                await self.session.scalars(
                    organization_query(EmployeeTrainingRecord, self.actor.organization_id).where(
                        EmployeeTrainingRecord.id == training_id
                    )
                )
            ).one_or_none()
            if record is None:
                raise NotFoundError("Training record not found")
            data = body.model_dump(exclude_unset=True)
            start = data.get("start_date", record.start_date)
            completion = data.get("completion_date", record.completion_date)
            if start and completion and completion < start:
                raise ValidationError("Training completion cannot precede start")
            if data.get("document_id") is not None:
                await self._document_or_404(data["document_id"], record.employee_id)
            for key, value in data.items():
                setattr(record, key, value)
            record.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.training_updated",
                entity_type="employee_training_record",
                entity_id=record.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeTrainingRead.model_validate(record)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def expiring(self, days: int) -> Sequence[TrainingExpiringRead]:
        return await self._expiring(days, only_compliance=False)

    async def compliance(self, days: int) -> Sequence[TrainingExpiringRead]:
        return await self._expiring(days, only_compliance=True)

    async def _expiring(self, days: int, only_compliance: bool) -> Sequence[TrainingExpiringRead]:
        cutoff = date.today() + timedelta(days=days)
        query = organization_query(EmployeeTrainingRecord, self.actor.organization_id).where(
            EmployeeTrainingRecord.expiry_date.is_not(None),
            EmployeeTrainingRecord.expiry_date <= cutoff,
            EmployeeTrainingRecord.is_active == True,  # noqa: E712
        )
        if only_compliance:
            query = query.where(
                EmployeeTrainingRecord.status.in_(
                    [TrainingStatus.COMPLETED, TrainingStatus.EXPIRED]
                )
            )
        rows = (
            await self.session.scalars(query.order_by(EmployeeTrainingRecord.expiry_date))
        ).all()
        employee_ids = {row.employee_id for row in rows}
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
        result = []
        for row in rows:
            employee = by_id.get(row.employee_id)
            if employee is None or row.expiry_date is None:
                continue
            result.append(
                TrainingExpiringRead(
                    training=EmployeeTrainingRead.model_validate(row),
                    employee_number=employee.employee_number,
                    employee_name=f"{employee.first_name} {employee.last_name}",
                    days_until_expiry=(row.expiry_date - today).days,
                )
            )
        return result

    async def _document_or_404(self, document_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        document = (
            await self.session.scalars(
                organization_query(EmployeeDocument, self.actor.organization_id).where(
                    EmployeeDocument.id == document_id
                )
            )
        ).one_or_none()
        if document is None:
            raise NotFoundError("Document not found")
        if document.employee_id != employee_id:
            raise ValidationError("Document belongs to a different employee")


class LicenseService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeLicenseRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeLicense, self.actor.organization_id)
                .where(EmployeeLicense.employee_id == employee_id)
                .order_by(EmployeeLicense.expiry_date)
            )
        ).all()
        return [EmployeeLicenseRead.model_validate(row) for row in rows]

    async def create(
        self, employee_id: uuid.UUID, body: LicenseCreate, request: Request | None = None
    ) -> EmployeeLicenseRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            if body.expiry_date and body.issue_date and body.expiry_date < body.issue_date:
                raise ValidationError("Licence expiry cannot precede issue date")
            if body.document_id is not None:
                await self._document_or_404(body.document_id, employee_id)
            record = EmployeeLicense(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                license_type=body.license_type,
                license_number=body.license_number,
                issuing_authority=body.issuing_authority,
                issuing_country=body.issuing_country,
                issue_date=body.issue_date,
                expiry_date=body.expiry_date,
                status=body.status,
                document_id=body.document_id,
                restrictions=body.restrictions,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(record)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.license_added",
                entity_type="employee_license",
                entity_id=record.id,
                new_values={"employee_id": str(employee_id)},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeLicenseRead.model_validate(record)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, license_id: uuid.UUID, body: LicenseUpdate, request: Request | None = None
    ) -> EmployeeLicenseRead:
        try:
            record = (
                await self.session.scalars(
                    organization_query(EmployeeLicense, self.actor.organization_id).where(
                        EmployeeLicense.id == license_id
                    )
                )
            ).one_or_none()
            if record is None:
                raise NotFoundError("Licence not found")
            data = body.model_dump(exclude_unset=True)
            issue = data.get("issue_date", record.issue_date)
            expiry = data.get("expiry_date", record.expiry_date)
            if issue and expiry and expiry < issue:
                raise ValidationError("Licence expiry cannot precede issue date")
            if data.get("document_id") is not None:
                await self._document_or_404(data["document_id"], record.employee_id)
            for key, value in data.items():
                setattr(record, key, value)
            record.updated_by_id = self.actor.id
            record.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.license_updated",
                entity_type="employee_license",
                entity_id=record.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeLicenseRead.model_validate(record)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def expiring(self, days: int) -> Sequence[LicenseExpiringRead]:
        cutoff = date.today() + timedelta(days=days)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeLicense, self.actor.organization_id)
                .where(
                    EmployeeLicense.expiry_date.is_not(None),
                    EmployeeLicense.expiry_date <= cutoff,
                    EmployeeLicense.is_active == True,  # noqa: E712
                )
                .order_by(EmployeeLicense.expiry_date)
            )
        ).all()
        employee_ids = {row.employee_id for row in rows}
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
        result = []
        for row in rows:
            employee = by_id.get(row.employee_id)
            if employee is None or row.expiry_date is None:
                continue
            result.append(
                LicenseExpiringRead(
                    license=EmployeeLicenseRead.model_validate(row),
                    employee_number=employee.employee_number,
                    employee_name=f"{employee.first_name} {employee.last_name}",
                    days_until_expiry=(row.expiry_date - today).days,
                )
            )
        return result

    async def _document_or_404(self, document_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        document = (
            await self.session.scalars(
                organization_query(EmployeeDocument, self.actor.organization_id).where(
                    EmployeeDocument.id == document_id
                )
            )
        ).one_or_none()
        if document is None:
            raise NotFoundError("Document not found")
        if document.employee_id != employee_id:
            raise ValidationError("Document belongs to a different employee")


class RotationService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list_patterns(self) -> Sequence[RotationPatternRead]:
        rows = (
            await self.session.scalars(
                organization_query(RotationPattern, self.actor.organization_id).order_by(
                    RotationPattern.name
                )
            )
        ).all()
        return [RotationPatternRead.model_validate(row) for row in rows]

    async def create_pattern(self, body: RotationPatternCreate) -> RotationPatternRead:
        try:
            pattern = RotationPattern(
                organization_id=self.actor.organization_id,
                name=body.name,
                days_on=body.days_on,
                days_off=body.days_off,
                description=body.description,
            )
            self.session.add(pattern)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.rotation_created",
                entity_type="rotation_pattern",
                entity_id=pattern.id,
                new_values={"name": body.name},
            )
            await self.session.commit()
            return RotationPatternRead.model_validate(pattern)
        except (ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update_pattern(
        self, pattern_id: uuid.UUID, body: RotationPatternUpdate
    ) -> RotationPatternRead:
        try:
            pattern = (
                await self.session.scalars(
                    organization_query(RotationPattern, self.actor.organization_id).where(
                        RotationPattern.id == pattern_id
                    )
                )
            ).one_or_none()
            if pattern is None:
                raise NotFoundError("Rotation pattern not found")
            for key, value in body.model_dump(exclude_unset=True).items():
                setattr(pattern, key, value)
            pattern.updated_at = datetime.now(UTC)
            await self.session.flush()
            await self.session.commit()
            return RotationPatternRead.model_validate(pattern)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def list_rotations(self, employee_id: uuid.UUID) -> Sequence[EmployeeRotationRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        return await self._rotation_reads(
            organization_query(EmployeeRotation, self.actor.organization_id)
            .where(EmployeeRotation.employee_id == employee_id)
            .order_by(EmployeeRotation.work_start_date.desc())
        )

    async def create_rotation(
        self, employee_id: uuid.UUID, body: EmployeeRotationCreate, request: Request | None = None
    ) -> EmployeeRotationRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            pattern = (
                await self.session.scalars(
                    organization_query(RotationPattern, self.actor.organization_id).where(
                        RotationPattern.id == body.rotation_pattern_id
                    )
                )
            ).one_or_none()
            if pattern is None:
                raise NotFoundError("Rotation pattern not found")
            if body.project_id is not None:
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
            if body.assignment_id is not None:
                assignment = (
                    await self.session.scalars(
                        select(EmployeeAssignment).where(
                            EmployeeAssignment.id == body.assignment_id,
                            EmployeeAssignment.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if assignment is None:
                    raise NotFoundError("Assignment not found")
                if assignment.employee_id != employee_id:
                    raise ValidationError("Assignment belongs to a different employee")
            self._check_chronology(body)
            rotation = EmployeeRotation(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                project_id=body.project_id,
                assignment_id=body.assignment_id,
                rotation_pattern_id=body.rotation_pattern_id,
                cycle_start_date=body.cycle_start_date,
                work_start_date=body.work_start_date,
                work_end_date=body.work_end_date,
                off_start_date=body.off_start_date,
                off_end_date=body.off_end_date,
                status=body.status,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(rotation)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.rotation_created",
                entity_type="employee_rotation",
                entity_id=rotation.id,
                new_values={"employee_id": str(employee_id)},
                **_meta(request),
            )
            await self.session.commit()
            reads = await self._rotation_reads(
                organization_query(EmployeeRotation, self.actor.organization_id).where(
                    EmployeeRotation.id == rotation.id
                )
            )
            return reads[0]
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def current(self, project_id: uuid.UUID | None = None) -> Sequence[EmployeeRotationRead]:
        """Rotations covering today: who is on site right now."""
        today = date.today()
        query = organization_query(EmployeeRotation, self.actor.organization_id).where(
            EmployeeRotation.work_start_date <= today,
            EmployeeRotation.work_end_date >= today,
            EmployeeRotation.status == RotationStatus.ON_SITE,
        )
        if project_id is not None:
            query = query.where(EmployeeRotation.project_id == project_id)
        return await self._rotation_reads(query.order_by(EmployeeRotation.work_end_date))

    async def upcoming(
        self, days: int, project_id: uuid.UUID | None = None
    ) -> Sequence[EmployeeRotationRead]:
        """Rotations starting within the window: who returns next."""
        today = date.today()
        query = organization_query(EmployeeRotation, self.actor.organization_id).where(
            EmployeeRotation.work_start_date > today,
            EmployeeRotation.work_start_date <= today + timedelta(days=days),
            EmployeeRotation.status == RotationStatus.PLANNED,
        )
        if project_id is not None:
            query = query.where(EmployeeRotation.project_id == project_id)
        return await self._rotation_reads(query.order_by(EmployeeRotation.work_start_date))

    async def _rotation_reads(
        self, query: Select[tuple[EmployeeRotation]]
    ) -> list[EmployeeRotationRead]:
        rows = (await self.session.scalars(query)).all()
        pattern_ids = {row.rotation_pattern_id for row in rows}
        patterns = (
            (
                await self.session.scalars(
                    organization_query(RotationPattern, self.actor.organization_id).where(
                        RotationPattern.id.in_(pattern_ids)
                    )
                )
            ).all()
            if pattern_ids
            else []
        )
        names = {p.id: p.name for p in patterns}
        reads = []
        for row in rows:
            read = EmployeeRotationRead.model_validate(row)
            read.rotation_pattern_name = names.get(row.rotation_pattern_id)
            reads.append(read)
        return reads

    def _check_chronology(self, body: EmployeeRotationCreate) -> None:
        if not (
            body.cycle_start_date
            <= body.work_start_date
            <= body.work_end_date
            <= body.off_start_date
            <= body.off_end_date
        ):
            raise ValidationError(
                "Rotation dates must run cycle, work, then off in chronological order"
            )


class AuthorizationService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list(self, employee_id: uuid.UUID) -> Sequence[EmployeeAssetAuthorizationRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(EmployeeAssetAuthorization, self.actor.organization_id)
                .where(EmployeeAssetAuthorization.employee_id == employee_id)
                .order_by(EmployeeAssetAuthorization.created_at)
            )
        ).all()
        return [EmployeeAssetAuthorizationRead.model_validate(row) for row in rows]

    async def create(
        self,
        employee_id: uuid.UUID,
        body: AssetAuthorizationCreate,
        request: Request | None = None,
    ) -> EmployeeAssetAuthorizationRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            if body.asset_category_id is None and body.asset_id is None:
                raise ValidationError("Authorization needs an asset category or a specific asset")
            if body.asset_category_id is not None:
                category = (
                    await self.session.scalars(
                        select(AssetCategory).where(
                            AssetCategory.id == body.asset_category_id,
                            AssetCategory.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if category is None:
                    raise NotFoundError("Asset category not found")
            if body.asset_id is not None:
                asset = (
                    await self.session.scalars(
                        select(Asset).where(
                            Asset.id == body.asset_id,
                            Asset.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if asset is None:
                    raise NotFoundError("Asset not found")
            if body.valid_from and body.valid_until and body.valid_until < body.valid_from:
                raise ValidationError("Authorization end cannot precede start")
            authorization = EmployeeAssetAuthorization(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                asset_category_id=body.asset_category_id,
                asset_id=body.asset_id,
                authorization_type=body.authorization_type,
                valid_from=body.valid_from,
                valid_until=body.valid_until,
                authorized_by_id=self.actor.id,
                status=body.status,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(authorization)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.asset_authorization_created",
                entity_type="employee_asset_authorization",
                entity_id=authorization.id,
                new_values={"employee_id": str(employee_id)},
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeAssetAuthorizationRead.model_validate(authorization)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self,
        authorization_id: uuid.UUID,
        body: AssetAuthorizationUpdate,
        request: Request | None = None,
    ) -> EmployeeAssetAuthorizationRead:
        try:
            authorization = (
                await self.session.scalars(
                    organization_query(
                        EmployeeAssetAuthorization, self.actor.organization_id
                    ).where(EmployeeAssetAuthorization.id == authorization_id)
                )
            ).one_or_none()
            if authorization is None:
                raise NotFoundError("Authorization not found")
            data = body.model_dump(exclude_unset=True)
            valid_from = data.get("valid_from", authorization.valid_from)
            valid_until = data.get("valid_until", authorization.valid_until)
            if valid_from and valid_until and valid_until < valid_from:
                raise ValidationError("Authorization end cannot precede start")
            for key, value in data.items():
                setattr(authorization, key, value)
            authorization.updated_by_id = self.actor.id
            authorization.updated_at = datetime.now(UTC)
            await self.session.flush()
            await self.session.commit()
            return EmployeeAssetAuthorizationRead.model_validate(authorization)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def revoke(
        self, authorization_id: uuid.UUID, request: Request | None = None
    ) -> EmployeeAssetAuthorizationRead:
        try:
            authorization = (
                await self.session.scalars(
                    organization_query(
                        EmployeeAssetAuthorization, self.actor.organization_id
                    ).where(EmployeeAssetAuthorization.id == authorization_id)
                )
            ).one_or_none()
            if authorization is None:
                raise NotFoundError("Authorization not found")
            authorization.status = AuthorizationStatus.REVOKED
            authorization.updated_by_id = self.actor.id
            authorization.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="employee.asset_authorization_revoked",
                entity_type="employee_asset_authorization",
                entity_id=authorization.id,
                **_meta(request),
            )
            await self.session.commit()
            return EmployeeAssetAuthorizationRead.model_validate(authorization)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise


class TimeLogService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def create(
        self, employee_id: uuid.UUID, body: TimeLogCreate, request: Request | None = None
    ) -> TimeLogRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            time_log = TimeLog(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                date=body.date,
                check_in=body.check_in,
                check_out=body.check_out,
                status=TimeLogStatus.COMPLETED if body.check_out else TimeLogStatus.PENDING,
                notes=body.notes,
                logged_by_id=self.actor.id,
            )
            self.session.add(time_log)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="time_log.created",
                entity_type="time_log",
                entity_id=time_log.id,
                new_values={"employee_id": str(employee_id), "date": str(body.date)},
                **_meta(request),
            )
            await self.session.commit()
            return TimeLogRead.model_validate(time_log)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def list(self, employee_id: uuid.UUID) -> Sequence[TimeLogRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(TimeLog, self.actor.organization_id)
                .where(TimeLog.employee_id == employee_id)
                .order_by(TimeLog.date.desc())
            )
        ).all()
        return [TimeLogRead.model_validate(row) for row in rows]


class LeaveRequestService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def create(
        self, employee_id: uuid.UUID, body: LeaveRequestCreate, request: Request | None = None
    ) -> LeaveRequestRead:
        try:
            await _employee_or_404(self.session, self.actor, employee_id)
            # Serialize overlapping bookings for the same employee.
            await self.session.execute(
                select(Employee).where(Employee.id == employee_id, Employee.organization_id == self.actor.organization_id).with_for_update()
            )
            # Check for overlapping leave requests
            existing = (
                await self.session.scalars(
                    organization_query(LeaveRequest, self.actor.organization_id)
                    .where(LeaveRequest.employee_id == employee_id)
                    .where(LeaveRequest.status.in_(["PENDING", "APPROVED"]))
                )
            ).all()
            for req in existing:
                if req.start_date <= body.end_date and req.end_date >= body.start_date:
                    raise ValidationError("Leave request overlaps with an existing request")

            leave = LeaveRequest(
                organization_id=self.actor.organization_id,
                employee_id=employee_id,
                start_date=body.start_date,
                end_date=body.end_date,
                reason=body.reason,
                attachment_url=body.attachment,
                status=LeaveRequestStatus.PENDING,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(leave)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="leave_request.created",
                entity_type="leave_request",
                entity_id=leave.id,
                new_values={
                    "employee_id": str(employee_id),
                    "start_date": str(body.start_date),
                    "end_date": str(body.end_date),
                },
                **_meta(request),
            )
            await self.session.commit()
            return LeaveRequestRead.model_validate(leave)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def list(self, employee_id: uuid.UUID) -> Sequence[LeaveRequestRead]:
        await _employee_or_404(self.session, self.actor, employee_id)
        rows = (
            await self.session.scalars(
                organization_query(LeaveRequest, self.actor.organization_id)
                .where(LeaveRequest.employee_id == employee_id)
                .order_by(LeaveRequest.start_date.desc())
            )
        ).all()
        return [LeaveRequestRead.model_validate(row) for row in rows]

    async def update(
        self,
        leave_id: uuid.UUID,
        body: LeaveRequestUpdate,
        request: Request | None = None,
    ) -> LeaveRequestRead:
        try:
            leave = (
                await self.session.scalars(
                    organization_query(LeaveRequest, self.actor.organization_id)
                    .where(LeaveRequest.id == leave_id)
                    .with_for_update()
                )
            ).one_or_none()
            if not leave:
                raise NotFoundError("Leave request not found")
            
            if body.status not in ("APPROVED", "REJECTED"):
                raise ValidationError("Choose approve or reject")
            if leave.status != LeaveRequestStatus.PENDING:
                raise ConflictError("Only pending leave requests can be decided")
            leave.status = LeaveRequestStatus(body.status)
            if leave.status == LeaveRequestStatus.APPROVED:
                leave.approved_by_id = self.actor.id
                leave.approved_at = datetime.now(UTC)

            leave.updated_by_id = self.actor.id
            leave.updated_at = datetime.now(UTC)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="leave_request.updated",
                entity_type="leave_request",
                entity_id=leave.id,
                new_values={"status": leave.status, "employee_id": str(leave.employee_id)},
                **_meta(request),
            )
            await self.session.commit()
            return LeaveRequestRead.model_validate(leave)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise
