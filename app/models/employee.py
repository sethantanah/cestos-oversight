import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy import Text as SAText
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import (
    ActorMixin,
    ArchiveMixin,
    OrganizationMixin,
    TimestampMixin,
    UUIDMixin,
)


class EmploymentType(enum.StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    CASUAL = "CASUAL"
    TEMPORARY = "TEMPORARY"
    CONSULTANT = "CONSULTANT"
    INTERN = "INTERN"


class EmploymentStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    OFF_ROTATION = "OFF_ROTATION"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"
    RESIGNED = "RESIGNED"
    TERMINATED = "TERMINATED"
    RETIRED = "RETIRED"
    DECEASED = "DECEASED"


class MaritalStatus(enum.StrEnum):
    SINGLE = "SINGLE"
    MARRIED = "MARRIED"
    DIVORCED = "DIVORCED"
    WIDOWED = "WIDOWED"
    SEPARATED = "SEPARATED"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DocumentType(enum.StrEnum):
    CV = "CV"
    NATIONAL_ID = "NATIONAL_ID"
    PASSPORT = "PASSPORT"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    WORK_PERMIT = "WORK_PERMIT"
    EMPLOYMENT_CONTRACT = "EMPLOYMENT_CONTRACT"
    MEDICAL_CERTIFICATE = "MEDICAL_CERTIFICATE"
    SAFETY_CERTIFICATE = "SAFETY_CERTIFICATE"
    TRAINING_CERTIFICATE = "TRAINING_CERTIFICATE"
    EDUCATIONAL_CERTIFICATE = "EDUCATIONAL_CERTIFICATE"
    TRADE_CERTIFICATE = "TRADE_CERTIFICATE"
    PROFESSIONAL_CERTIFICATE = "PROFESSIONAL_CERTIFICATE"
    INSURANCE_DOCUMENT = "INSURANCE_DOCUMENT"
    POLICE_CLEARANCE = "POLICE_CLEARANCE"
    OTHER = "OTHER"


class VerificationStatus(enum.StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RelationshipType(enum.StrEnum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"
    GUARDIAN = "GUARDIAN"
    PARTNER = "PARTNER"
    RELATIVE = "RELATIVE"
    OTHER = "OTHER"


class ProficiencyLevel(enum.StrEnum):
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"
    CERTIFIED = "CERTIFIED"


class TrainingStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class LicenseType(enum.StrEnum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    HEAVY_EQUIPMENT_OPERATOR = "HEAVY_EQUIPMENT_OPERATOR"
    DRILL_RIG_OPERATOR = "DRILL_RIG_OPERATOR"
    FORKLIFT_LICENSE = "FORKLIFT_LICENSE"
    WORK_PERMIT = "WORK_PERMIT"
    PROFESSIONAL_REGISTRATION = "PROFESSIONAL_REGISTRATION"
    OTHER = "OTHER"


class LicenseStatus(enum.StrEnum):
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"


class AssignmentStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentType(enum.StrEnum):
    PROJECT = "PROJECT"
    SITE = "SITE"
    TEMPORARY = "TEMPORARY"
    RELIEF = "RELIEF"
    TRAINING = "TRAINING"
    OFFICE = "OFFICE"
    OTHER = "OTHER"


class RotationStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    ON_SITE = "ON_SITE"
    OFF_ROTATION = "OFF_ROTATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AuthorizationType(enum.StrEnum):
    OPERATOR = "OPERATOR"
    DRIVER = "DRIVER"
    MAINTENANCE = "MAINTENANCE"
    INSPECTOR = "INSPECTOR"
    SUPERVISOR = "SUPERVISOR"
    OTHER = "OTHER"


class AuthorizationStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class AvailabilityStatus(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    ON_LEAVE = "ON_LEAVE"
    OFF_ROTATION = "OFF_ROTATION"
    TRAINING = "TRAINING"
    SUSPENDED = "SUSPENDED"
    UNAVAILABLE = "UNAVAILABLE"


class TimeLogStatus(enum.StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LeaveRequestStatus(enum.StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ComplianceStatus(enum.StrEnum):
    COMPLIANT = "COMPLIANT"
    WARNING = "WARNING"
    NON_COMPLIANT = "NON_COMPLIANT"


class Department(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        Index("ix_departments_org_name", "organization_id", "name", unique=True),
        Index("ix_departments_org_parent", "organization_id", "parent_department_id"),
    )

    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(SAText)
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    parent_department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))


class Position(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_positions_org_title", "organization_id", "title", unique=True),
        Index("ix_positions_org_department", "organization_id", "department_id"),
    )

    title: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(50))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    description: Mapped[str | None] = mapped_column(SAText)
    grade: Mapped[str | None] = mapped_column(String(50))
    level: Mapped[str | None] = mapped_column(String(50))
    is_field_role: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Employee(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        Index("ix_employees_org_number", "organization_id", "employee_number", unique=True),
        Index("ix_employees_org_work_email", "organization_id", "work_email", unique=True),
        Index("ix_employees_org_status", "organization_id", "employment_status"),
        Index("ix_employees_org_department", "organization_id", "department_id"),
        Index("ix_employees_org_position", "organization_id", "position_id"),
        Index("ix_employees_org_supervisor", "organization_id", "supervisor_id"),
        Index("ix_employees_last_name", "organization_id", "last_name"),
        CheckConstraint(
            "termination_date IS NULL OR hire_date IS NULL OR termination_date >= hire_date",
            name="termination_after_hire",
        ),
        CheckConstraint(
            "contract_end_date IS NULL OR contract_start_date IS NULL "
            "OR contract_end_date >= contract_start_date",
            name="contract_dates",
        ),
        CheckConstraint("work_email = lower(work_email)", name="ck_employees_email_lowercase"),
    )

    employee_number: Mapped[str] = mapped_column(String(30))
    first_name: Mapped[str] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    preferred_name: Mapped[str | None] = mapped_column(String(100))
    gender: Mapped[str | None] = mapped_column(String(30))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(100))
    marital_status: Mapped[MaritalStatus | None] = mapped_column(
        Enum(MaritalStatus, name="marital_status")
    )
    personal_email: Mapped[str | None] = mapped_column(String(255))
    work_email: Mapped[str | None] = mapped_column(String(320), index=True)
    primary_phone: Mapped[str | None] = mapped_column(String(50))
    secondary_phone: Mapped[str | None] = mapped_column(String(50))
    residential_address: Mapped[str | None] = mapped_column(SAText)
    city: Mapped[str | None] = mapped_column(String(100))
    county_or_region: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("positions.id"))
    department: Mapped[str | None] = mapped_column(String(150))
    job_title: Mapped[str | None] = mapped_column(String(150))
    employment_type: Mapped[EmploymentType] = mapped_column(
        Enum(EmploymentType, name="employment_type"), default=EmploymentType.FULL_TIME
    )
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        Enum(EmploymentStatus, name="employment_status"), default=EmploymentStatus.ACTIVE
    )
    hire_date: Mapped[date | None] = mapped_column(Date)
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)
    contract_start_date: Mapped[date | None] = mapped_column(Date)
    contract_end_date: Mapped[date | None] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    termination_reason: Mapped[str | None] = mapped_column(SAText)
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    home_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), unique=True)
    profile_photo_url: Mapped[str | None] = mapped_column(SAText)
    bio: Mapped[str | None] = mapped_column(SAText)
    notes: Mapped[str | None] = mapped_column(SAText)

    supervisor: Mapped["Employee | None"] = relationship(
        "Employee", remote_side="Employee.id", lazy="raise"
    )


class EmployeeFamilyMember(
    UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base
):
    __tablename__ = "employee_family_members"
    __table_args__ = (
        Index("ix_family_employee", "organization_id", "employee_id"),
        Index("ix_family_dependent", "organization_id", "employee_id", "is_dependent"),
        Index("ix_family_next_of_kin", "organization_id", "employee_id", "is_next_of_kin"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    relationship_type: Mapped[RelationshipType] = mapped_column(
        Enum(RelationshipType, name="relationship_type")
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(30))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(SAText)
    occupation: Mapped[str | None] = mapped_column(String(150))
    employer: Mapped[str | None] = mapped_column(String(200))
    is_dependent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_next_of_kin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_primary_next_of_kin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_emergency_contact: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    dependency_start_date: Mapped[date | None] = mapped_column(Date)
    dependency_end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(SAText)


class EmployeeEmergencyContact(
    UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base
):
    __tablename__ = "employee_emergency_contacts"
    __table_args__ = (
        Index("ix_emergency_employee", "organization_id", "employee_id"),
        Index("ix_emergency_primary", "organization_id", "employee_id", "is_primary"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    family_member_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employee_family_members.id")
    )
    full_name: Mapped[str] = mapped_column(String(200))
    relationship: Mapped[str | None] = mapped_column(String(100))
    primary_phone: Mapped[str] = mapped_column(String(50))
    secondary_phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(SAText)
    priority: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(SAText)


class EmployeeResume(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "employee_resumes"
    __table_args__ = (
        Index("ix_resumes_employee", "organization_id", "employee_id"),
        Index("ix_resumes_current", "organization_id", "employee_id", "is_current"),
        Index(
            "uq_resumes_employee_version", "organization_id", "employee_id", "version", unique=True
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    file_url: Mapped[str] = mapped_column(String(1024))
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(SAText)


class EmployeeDocument(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "employee_documents"
    __table_args__ = (
        Index("ix_employee_documents_employee", "organization_id", "employee_id"),
        Index("ix_employee_documents_type", "organization_id", "document_type"),
        Index("ix_employee_documents_expiry", "organization_id", "expiry_date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="document_type"), default=DocumentType.OTHER
    )
    title: Mapped[str] = mapped_column(String(200))
    document_number: Mapped[str | None] = mapped_column(String(100))
    file_url: Mapped[str] = mapped_column(String(1024))
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    issuing_authority: Mapped[str | None] = mapped_column(String(200))
    issuing_country: Mapped[str | None] = mapped_column(String(100))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status"),
        default=VerificationStatus.PENDING,
        server_default="PENDING",
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(SAText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class EmployeeQualification(
    UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base
):
    __tablename__ = "employee_qualifications"
    __table_args__ = (Index("ix_qualifications_employee", "organization_id", "employee_id"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    qualification_type: Mapped[str] = mapped_column(String(100))
    qualification_name: Mapped[str] = mapped_column(String(200))
    institution: Mapped[str | None] = mapped_column(String(200))
    field_of_study: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    grade_or_classification: Mapped[str | None] = mapped_column(String(100))
    certificate_number: Mapped[str | None] = mapped_column(String(100))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee_documents.id"))
    notes: Mapped[str | None] = mapped_column(SAText)


class Skill(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (Index("ix_skills_org_name", "organization_id", "name", unique=True),)

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(SAText)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class EmployeeSkill(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "employee_skills"
    __table_args__ = (
        Index(
            "uq_employee_skills_employee_skill",
            "organization_id",
            "employee_id",
            "skill_id",
            unique=True,
        ),
        Index("ix_employee_skills_skill", "organization_id", "skill_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id"))
    proficiency_level: Mapped[ProficiencyLevel | None] = mapped_column(
        Enum(ProficiencyLevel, name="proficiency_level")
    )
    years_experience: Mapped[int | None] = mapped_column(Integer)
    certification_number: Mapped[str | None] = mapped_column(String(100))
    certification_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(SAText)


class EmployeeTrainingRecord(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "employee_training_records"
    __table_args__ = (
        Index("ix_training_employee", "organization_id", "employee_id"),
        Index("ix_training_expiry", "organization_id", "expiry_date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    training_name: Mapped[str] = mapped_column(String(200))
    training_type: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[TrainingStatus] = mapped_column(
        Enum(TrainingStatus, name="training_status"), default=TrainingStatus.PLANNED
    )
    certificate_number: Mapped[str | None] = mapped_column(String(100))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee_documents.id"))
    notes: Mapped[str | None] = mapped_column(SAText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class EmployeeLicense(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "employee_licenses"
    __table_args__ = (
        Index("ix_licenses_employee", "organization_id", "employee_id"),
        Index("ix_licenses_expiry", "organization_id", "expiry_date"),
        Index("ix_licenses_type", "organization_id", "license_type"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    license_type: Mapped[LicenseType] = mapped_column(Enum(LicenseType, name="license_type"))
    license_number: Mapped[str] = mapped_column(String(100))
    issuing_authority: Mapped[str | None] = mapped_column(String(200))
    issuing_country: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[LicenseStatus] = mapped_column(
        Enum(LicenseStatus, name="license_status"), default=LicenseStatus.PENDING_VERIFICATION
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee_documents.id"))
    restrictions: Mapped[str | None] = mapped_column(SAText)
    notes: Mapped[str | None] = mapped_column(SAText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class RotationPattern(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "rotation_patterns"
    __table_args__ = (
        Index("ix_rotation_patterns_org_name", "organization_id", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(50))
    days_on: Mapped[int] = mapped_column(Integer)
    days_off: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(SAText)


class EmployeeRotation(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "employee_rotations"
    __table_args__ = (
        Index("ix_rotations_employee", "organization_id", "employee_id", "status"),
        Index("ix_rotations_pattern", "organization_id", "rotation_pattern_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee_assignments.id"))
    rotation_pattern_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rotation_patterns.id"))
    cycle_start_date: Mapped[date] = mapped_column(Date)
    work_start_date: Mapped[date] = mapped_column(Date)
    work_end_date: Mapped[date] = mapped_column(Date)
    off_start_date: Mapped[date] = mapped_column(Date)
    off_end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[RotationStatus] = mapped_column(
        Enum(RotationStatus, name="rotation_status"), default=RotationStatus.PLANNED
    )
    notes: Mapped[str | None] = mapped_column(SAText)


class EmployeeAssignment(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "employee_assignments"
    __table_args__ = (
        Index(
            "ix_employee_assignments_number", "organization_id", "assignment_number", unique=True
        ),
        Index("ix_employee_assignments_employee", "organization_id", "employee_id", "status"),
        Index("ix_employee_assignments_project", "organization_id", "project_id", "status"),
    )

    assignment_number: Mapped[str] = mapped_column(String(20))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("positions.id"))
    role_on_project: Mapped[str | None] = mapped_column(String(150))
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    assignment_type: Mapped[AssignmentType] = mapped_column(
        Enum(AssignmentType, name="assignment_type"),
        default=AssignmentType.PROJECT,
        server_default="PROJECT",
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, name="assignment_status"), default=AssignmentStatus.PLANNED
    )
    rotation_pattern_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rotation_patterns.id")
    )
    rotation_pattern: Mapped[str | None] = mapped_column(String(100))
    mobilization_date: Mapped[date | None] = mapped_column(Date)
    demobilization_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(SAText)


class EmployeeAssetAuthorization(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "employee_asset_authorizations"
    __table_args__ = (
        Index("ix_authorizations_employee", "organization_id", "employee_id", "status"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    asset_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_categories.id"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    authorization_type: Mapped[AuthorizationType] = mapped_column(
        Enum(AuthorizationType, name="authorization_type")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    authorized_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[AuthorizationStatus] = mapped_column(
        Enum(AuthorizationStatus, name="authorization_status"),
        default=AuthorizationStatus.ACTIVE,
    )
    notes: Mapped[str | None] = mapped_column(SAText)


class TimeLog(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "time_logs"
    __table_args__ = (
        Index("ix_timelogs_employee", "organization_id", "employee_id"),
        Index("ix_timelogs_date", "organization_id", "date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[TimeLogStatus] = mapped_column(
        Enum(TimeLogStatus, name="time_log_status"), default=TimeLogStatus.PENDING
    )
    notes: Mapped[str | None] = mapped_column(SAText)
    logged_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class LeaveRequest(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        Index("ix_leaves_employee", "organization_id", "employee_id"),
        Index("ix_leaves_status", "organization_id", "status"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(SAText)
    status: Mapped[LeaveRequestStatus] = mapped_column(
        Enum(LeaveRequestStatus, name="leave_request_status"), default=LeaveRequestStatus.PENDING
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attachment_url: Mapped[str | None] = mapped_column(String(1024))
    notes: Mapped[str | None] = mapped_column(SAText)
