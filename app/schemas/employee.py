import datetime as dt
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.employee import (
    AssignmentStatus,
    AssignmentType,
    AuthorizationStatus,
    AuthorizationType,
    AvailabilityStatus,
    ComplianceStatus,
    DocumentType,
    EmploymentStatus,
    EmploymentType,
    LicenseStatus,
    LicenseType,
    MaritalStatus,
    ProficiencyLevel,
    RelationshipType,
    RotationStatus,
    TrainingStatus,
    VerificationStatus,
    TimeLogStatus,
    LeaveRequestStatus,
)
from app.schemas.common import ORMModel

# ---------- departments & positions ----------


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=50)
    description: str | None = None
    manager_employee_id: uuid.UUID | None = None
    parent_department_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=50)
    description: str | None = None
    manager_employee_id: uuid.UUID | None = None
    parent_department_id: uuid.UUID | None = None
    is_active: bool | None = None


class DepartmentRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    manager_employee_id: uuid.UUID | None
    parent_department_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PositionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=50)
    department_id: uuid.UUID | None = None
    description: str | None = None
    grade: str | None = Field(default=None, max_length=50)
    level: str | None = Field(default=None, max_length=50)
    is_field_role: bool = False


class PositionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=50)
    department_id: uuid.UUID | None = None
    description: str | None = None
    grade: str | None = Field(default=None, max_length=50)
    level: str | None = Field(default=None, max_length=50)
    is_field_role: bool | None = None
    is_active: bool | None = None


class PositionRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    code: str | None
    department_id: uuid.UUID | None
    description: str | None
    grade: str | None
    level: str | None
    is_field_role: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------- employee master ----------


class EmployeeCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    gender: str | None = Field(default=None, max_length=30)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=100)
    marital_status: MaritalStatus | None = None
    personal_email: EmailStr | None = None
    work_email: EmailStr | None = None
    primary_phone: str | None = Field(default=None, max_length=50)
    secondary_phone: str | None = Field(default=None, max_length=50)
    residential_address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    county_or_region: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    department_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=150)
    job_title: str | None = Field(default=None, max_length=150)
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    hire_date: date | None = None
    probation_end_date: date | None = None
    confirmation_date: date | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    termination_date: date | None = None
    termination_reason: str | None = None
    supervisor_id: uuid.UUID | None = None
    home_location_id: uuid.UUID | None = None
    profile_photo_url: str | None = None
    bio: str | None = None
    notes: str | None = None


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    gender: str | None = Field(default=None, max_length=30)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=100)
    marital_status: MaritalStatus | None = None
    personal_email: EmailStr | None = None
    work_email: EmailStr | None = None
    primary_phone: str | None = Field(default=None, max_length=50)
    secondary_phone: str | None = Field(default=None, max_length=50)
    residential_address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    county_or_region: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    department_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=150)
    job_title: str | None = Field(default=None, max_length=150)
    employment_type: EmploymentType | None = None
    employment_status: EmploymentStatus | None = None
    hire_date: date | None = None
    probation_end_date: date | None = None
    confirmation_date: date | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    termination_date: date | None = None
    termination_reason: str | None = None
    supervisor_id: uuid.UUID | None = None
    home_location_id: uuid.UUID | None = None
    profile_photo_url: str | None = None
    bio: str | None = None
    notes: str | None = None


class EmployeeRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_number: str
    first_name: str
    middle_name: str | None
    last_name: str
    preferred_name: str | None
    gender: str | None
    date_of_birth: date | None
    nationality: str | None
    marital_status: MaritalStatus | None
    personal_email: str | None
    work_email: str | None
    primary_phone: str | None
    secondary_phone: str | None
    residential_address: str | None
    city: str | None
    county_or_region: str | None
    country: str | None
    department_id: uuid.UUID | None
    position_id: uuid.UUID | None
    department: str | None
    job_title: str | None
    employment_type: EmploymentType
    employment_status: EmploymentStatus
    hire_date: date | None
    probation_end_date: date | None
    confirmation_date: date | None
    contract_start_date: date | None
    contract_end_date: date | None
    termination_date: date | None
    termination_reason: str | None
    supervisor_id: uuid.UUID | None
    home_location_id: uuid.UUID | None
    profile_photo_url: str | None
    bio: str | None
    notes: str | None
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    availability_status: AvailabilityStatus | None = None


EmployeeListItem = EmployeeRead
EmployeeDetail = EmployeeRead


class EmployeeBasic(ORMModel):
    """Slim operational view: no family, addresses, or private HR data."""

    id: uuid.UUID
    organization_id: uuid.UUID
    employee_number: str
    full_name: str
    profile_photo_url: str | None
    job_title: str | None
    position_id: uuid.UUID | None
    department_id: uuid.UUID | None
    department: str | None
    primary_phone: str | None
    employment_status: EmploymentStatus
    availability_status: AvailabilityStatus | None = None
    current_project_id: uuid.UUID | None = None
    current_project_name: str | None = None
    current_location_id: uuid.UUID | None = None
    current_location_name: str | None = None


class EmployeeFull(EmployeeRead):
    """HR view: master plus family and emergency contacts."""

    family: list["EmployeeFamilyRead"] = []
    emergency_contacts: list["EmployeeEmergencyContactRead"] = []


# ---------- family ----------


class EmployeeFamilyCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    relationship_type: RelationshipType
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    address: str | None = None
    occupation: str | None = Field(default=None, max_length=150)
    employer: str | None = Field(default=None, max_length=200)
    is_dependent: bool = False
    is_next_of_kin: bool = False
    is_primary_next_of_kin: bool = False
    is_emergency_contact: bool = False
    dependency_start_date: date | None = None
    dependency_end_date: date | None = None
    notes: str | None = None


class EmployeeFamilyUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    relationship_type: RelationshipType | None = None
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    address: str | None = None
    occupation: str | None = Field(default=None, max_length=150)
    employer: str | None = Field(default=None, max_length=200)
    is_dependent: bool | None = None
    is_next_of_kin: bool | None = None
    is_primary_next_of_kin: bool | None = None
    is_emergency_contact: bool | None = None
    dependency_start_date: date | None = None
    dependency_end_date: date | None = None
    notes: str | None = None


class EmployeeFamilyRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    full_name: str
    relationship_type: RelationshipType
    date_of_birth: date | None
    gender: str | None
    phone: str | None
    email: str | None
    address: str | None
    occupation: str | None
    employer: str | None
    is_dependent: bool
    is_next_of_kin: bool
    is_primary_next_of_kin: bool
    is_emergency_contact: bool
    dependency_start_date: date | None
    dependency_end_date: date | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FamilySummary(ORMModel):
    spouse: str | None
    children_count: int
    dependants_count: int
    next_of_kin: list[str]
    primary_next_of_kin: str | None


# ---------- emergency contacts ----------


class EmergencyContactCreate(BaseModel):
    family_member_id: uuid.UUID | None = None
    full_name: str = Field(min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=100)
    primary_phone: str = Field(min_length=1, max_length=50)
    secondary_phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    address: str | None = None
    priority: int = Field(default=1, ge=1, le=10)
    is_primary: bool = False
    notes: str | None = None


class EmergencyContactUpdate(BaseModel):
    family_member_id: uuid.UUID | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=100)
    primary_phone: str | None = Field(default=None, min_length=1, max_length=50)
    secondary_phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    address: str | None = None
    priority: int | None = Field(default=None, ge=1, le=10)
    is_primary: bool | None = None
    notes: str | None = None


class EmployeeEmergencyContactRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    family_member_id: uuid.UUID | None
    full_name: str
    relationship: str | None
    primary_phone: str
    secondary_phone: str | None
    email: str | None
    address: str | None
    priority: int
    is_primary: bool
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------- resumes ----------


class EmployeeResumeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    file_url: str = Field(min_length=1, max_length=1024)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    file_size: int | None = Field(default=None, ge=0)
    notes: str | None = None


class EmployeeResumeRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    title: str
    file_url: str
    file_name: str | None
    mime_type: str | None
    file_size: int | None
    version: int
    is_current: bool
    uploaded_at: datetime
    uploaded_by_id: uuid.UUID | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EmployeeResumeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None


# ---------- documents ----------


class EmployeeDocumentCreate(BaseModel):
    document_type: DocumentType = DocumentType.OTHER
    title: str = Field(min_length=1, max_length=200)
    document_number: str | None = Field(default=None, max_length=100)
    file_url: str = Field(min_length=1, max_length=1024)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    file_size: int | None = Field(default=None, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    issuing_authority: str | None = Field(default=None, max_length=200)
    issuing_country: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class EmployeeDocumentUpdate(BaseModel):
    document_type: DocumentType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    document_number: str | None = Field(default=None, max_length=100)
    file_url: str | None = Field(default=None, min_length=1, max_length=1024)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    file_size: int | None = Field(default=None, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    issuing_authority: str | None = Field(default=None, max_length=200)
    issuing_country: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class EmployeeDocumentRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    document_type: DocumentType
    title: str
    document_number: str | None
    file_url: str
    file_name: str | None
    mime_type: str | None
    file_size: int | None
    issue_date: date | None
    expiry_date: date | None
    issuing_authority: str | None
    issuing_country: str | None
    verification_status: VerificationStatus
    verified_by_id: uuid.UUID | None
    verified_at: datetime | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DocumentExpiringRead(ORMModel):
    document: EmployeeDocumentRead
    employee_number: str
    employee_name: str
    days_until_expiry: int


# ---------- qualifications ----------


class QualificationCreate(BaseModel):
    qualification_type: str = Field(min_length=1, max_length=100)
    qualification_name: str = Field(min_length=1, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    completion_date: date | None = None
    grade_or_classification: str | None = Field(default=None, max_length=100)
    certificate_number: str | None = Field(default=None, max_length=100)
    document_id: uuid.UUID | None = None
    notes: str | None = None


class QualificationUpdate(BaseModel):
    qualification_type: str | None = Field(default=None, min_length=1, max_length=100)
    qualification_name: str | None = Field(default=None, min_length=1, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    completion_date: date | None = None
    grade_or_classification: str | None = Field(default=None, max_length=100)
    certificate_number: str | None = Field(default=None, max_length=100)
    document_id: uuid.UUID | None = None
    notes: str | None = None


class EmployeeQualificationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    qualification_type: str
    qualification_name: str
    institution: str | None
    field_of_study: str | None
    start_date: date | None
    completion_date: date | None
    grade_or_classification: str | None
    certificate_number: str | None
    document_id: uuid.UUID | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------- skills ----------


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    category: str | None = Field(default=None, max_length=100)
    description: str | None = None
    organization_id: uuid.UUID | None = None


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: str | None = Field(default=None, max_length=100)
    description: str | None = None
    is_active: bool | None = None


class SkillRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    category: str | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EmployeeSkillCreate(BaseModel):
    skill_id: uuid.UUID
    proficiency_level: ProficiencyLevel | None = None
    years_experience: int | None = Field(default=None, ge=0, le=80)
    certification_number: str | None = Field(default=None, max_length=100)
    certification_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class EmployeeSkillUpdate(BaseModel):
    proficiency_level: ProficiencyLevel | None = None
    years_experience: int | None = Field(default=None, ge=0, le=80)
    certification_number: str | None = Field(default=None, max_length=100)
    certification_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class EmployeeSkillRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    skill_id: uuid.UUID
    skill_name: str | None = None
    proficiency_level: ProficiencyLevel | None
    years_experience: int | None
    certification_number: str | None
    certification_date: date | None
    expiry_date: date | None
    verified_by_id: uuid.UUID | None
    verified_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------- training ----------


class TrainingCreate(BaseModel):
    training_name: str = Field(min_length=1, max_length=200)
    training_type: str | None = Field(default=None, max_length=100)
    provider: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    completion_date: date | None = None
    status: TrainingStatus = TrainingStatus.PLANNED
    certificate_number: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None
    score: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    document_id: uuid.UUID | None = None
    notes: str | None = None


class TrainingUpdate(BaseModel):
    training_name: str | None = Field(default=None, min_length=1, max_length=200)
    training_type: str | None = Field(default=None, max_length=100)
    provider: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    completion_date: date | None = None
    status: TrainingStatus | None = None
    certificate_number: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None
    score: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    document_id: uuid.UUID | None = None
    notes: str | None = None


class EmployeeTrainingRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    training_name: str
    training_type: str | None
    provider: str | None
    start_date: date | None
    completion_date: date | None
    status: TrainingStatus
    certificate_number: str | None
    expiry_date: date | None
    score: Decimal | None
    document_id: uuid.UUID | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TrainingExpiringRead(ORMModel):
    training: EmployeeTrainingRead
    employee_number: str
    employee_name: str
    days_until_expiry: int


# ---------- licenses ----------


class LicenseCreate(BaseModel):
    license_type: LicenseType
    license_number: str = Field(min_length=1, max_length=100)
    issuing_authority: str | None = Field(default=None, max_length=200)
    issuing_country: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: LicenseStatus = LicenseStatus.PENDING_VERIFICATION
    document_id: uuid.UUID | None = None
    restrictions: str | None = None
    notes: str | None = None


class LicenseUpdate(BaseModel):
    license_type: LicenseType | None = None
    license_number: str | None = Field(default=None, min_length=1, max_length=100)
    issuing_authority: str | None = Field(default=None, max_length=200)
    issuing_country: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: LicenseStatus | None = None
    document_id: uuid.UUID | None = None
    restrictions: str | None = None
    notes: str | None = None


class EmployeeLicenseRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    license_type: LicenseType
    license_number: str
    issuing_authority: str | None
    issuing_country: str | None
    issue_date: date | None
    expiry_date: date | None
    status: LicenseStatus
    document_id: uuid.UUID | None
    restrictions: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LicenseExpiringRead(ORMModel):
    license: EmployeeLicenseRead
    employee_number: str
    employee_name: str
    days_until_expiry: int


# ---------- assignments ----------


class EmployeeAssignmentCreate(BaseModel):
    project_id: uuid.UUID
    location_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    role_on_project: str | None = Field(default=None, max_length=150)
    supervisor_id: uuid.UUID | None = None
    assignment_type: AssignmentType = AssignmentType.PROJECT
    start_date: date
    end_date: date | None = None
    is_primary: bool = True
    status: AssignmentStatus = AssignmentStatus.ACTIVE
    rotation_pattern_id: uuid.UUID | None = None
    rotation_pattern: str | None = Field(default=None, max_length=100)
    mobilization_date: date | None = None
    demobilization_date: date | None = None
    notes: str | None = None


class EmployeeAssignmentUpdate(BaseModel):
    location_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    role_on_project: str | None = Field(default=None, max_length=150)
    supervisor_id: uuid.UUID | None = None
    assignment_type: AssignmentType | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_primary: bool | None = None
    status: AssignmentStatus | None = None
    rotation_pattern_id: uuid.UUID | None = None
    rotation_pattern: str | None = Field(default=None, max_length=100)
    mobilization_date: date | None = None
    demobilization_date: date | None = None
    notes: str | None = None


class EmployeeAssignmentRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    assignment_number: str
    employee_id: uuid.UUID
    project_id: uuid.UUID
    location_id: uuid.UUID | None
    position_id: uuid.UUID | None
    role_on_project: str | None
    supervisor_id: uuid.UUID | None
    assignment_type: AssignmentType
    start_date: date
    end_date: date | None
    is_primary: bool
    status: AssignmentStatus
    rotation_pattern_id: uuid.UUID | None
    rotation_pattern: str | None
    mobilization_date: date | None
    demobilization_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeTransferRequest(BaseModel):
    project_id: uuid.UUID
    location_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    role_on_project: str | None = Field(default=None, max_length=150)
    supervisor_id: uuid.UUID | None = None
    assignment_type: AssignmentType = AssignmentType.PROJECT
    start_date: date
    rotation_pattern_id: uuid.UUID | None = None
    notes: str | None = None


# ---------- rotations ----------


class RotationPatternCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    days_on: int = Field(ge=1, le=365)
    days_off: int = Field(ge=1, le=365)
    description: str | None = None


class RotationPatternUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    days_on: int | None = Field(default=None, ge=1, le=365)
    days_off: int | None = Field(default=None, ge=1, le=365)
    description: str | None = None
    is_active: bool | None = None


class RotationPatternRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    days_on: int
    days_off: int
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EmployeeRotationCreate(BaseModel):
    project_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    rotation_pattern_id: uuid.UUID
    cycle_start_date: date
    work_start_date: date
    work_end_date: date
    off_start_date: date
    off_end_date: date
    status: RotationStatus = RotationStatus.PLANNED
    notes: str | None = None


class EmployeeRotationUpdate(BaseModel):
    project_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    rotation_pattern_id: uuid.UUID | None = None
    cycle_start_date: date | None = None
    work_start_date: date | None = None
    work_end_date: date | None = None
    off_start_date: date | None = None
    off_end_date: date | None = None
    status: RotationStatus | None = None
    notes: str | None = None


class EmployeeRotationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    project_id: uuid.UUID | None
    assignment_id: uuid.UUID | None
    rotation_pattern_id: uuid.UUID
    rotation_pattern_name: str | None = None
    cycle_start_date: date
    work_start_date: date
    work_end_date: date
    off_start_date: date
    off_end_date: date
    status: RotationStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------- asset authorizations ----------


class AssetAuthorizationCreate(BaseModel):
    asset_category_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    authorization_type: AuthorizationType
    valid_from: date | None = None
    valid_until: date | None = None
    status: AuthorizationStatus = AuthorizationStatus.ACTIVE
    notes: str | None = None


class AssetAuthorizationUpdate(BaseModel):
    asset_category_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    authorization_type: AuthorizationType | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    status: AuthorizationStatus | None = None
    notes: str | None = None


class EmployeeAssetAuthorizationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    asset_category_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    authorization_type: AuthorizationType
    valid_from: date | None
    valid_until: date | None
    authorized_by_id: uuid.UUID | None
    status: AuthorizationStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeAssetAuthorizationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    asset_category_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    authorization_type: AuthorizationType
    valid_from: date | None
    valid_until: date | None
    authorized_by_id: uuid.UUID | None
    status: AuthorizationStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------- time logging ----------


class TimeLogCreate(BaseModel):
    date: dt.date = Field(..., description="Date of the time log")
    check_in: datetime | None = Field(default=None, description="Check-in datetime")
    check_out: datetime | None = Field(default=None, description="Check-out datetime")
    notes: str | None = Field(default=None, description="Additional notes")


    @model_validator(mode="after")
    def valid_times(self):
        if self.check_out and not self.check_in:
            raise ValueError("Check-in is required with check-out")
        for value in (self.check_in, self.check_out):
            if value and value.utcoffset() is None:
                raise ValueError("Check-in and check-out must include a timezone")
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in")
        if not self.check_in and not (self.notes and self.notes.strip()):
            raise ValueError("Enter activity notes or a check-in time")
        return self


class TimeLogRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    date: dt.date
    check_in: datetime | None
    check_out: datetime | None
    status: str
    notes: str | None
    logged_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


# ---------- leave requests ----------


class LeaveRequestCreate(BaseModel):
    start_date: date = Field(..., description="Leave start date")
    end_date: date = Field(..., description="Leave end date")
    reason: str | None = Field(default=None, description="Reason for leave")
    attachment: str | None = Field(
        default=None, description="URL or path to leave letter attachment"
    )


    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("Leave end date must be on or after start date")
        return self


class LeaveRequestUpdate(BaseModel):
    start_date: date | None = Field(default=None, description="Leave start date")
    end_date: date | None = Field(default=None, description="Leave end date")
    reason: str | None = Field(default=None, description="Reason for leave")
    status: str | None = Field(
        default=None, description="Status: PENDING, APPROVED, REJECTED"
    )
    attachment: str | None = Field(
        default=None, description="URL or path to leave letter attachment"
    )


class LeaveRequestRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str | None
    status: str
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None
    attachment_url: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------- overview / dashboard ----------


class ComplianceIssue(ORMModel):
    rule: str
    severity: str
    message: str


class ComplianceResult(ORMModel):
    status: ComplianceStatus
    issues: list[ComplianceIssue]


class ActivityEntry(ORMModel):
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    occurred_at: datetime
    summary: str | None = None


class EmployeeOverview(ORMModel):
    employee: EmployeeRead
    department: DepartmentRead | None
    position: PositionRead | None
    supervisor: EmployeeRead | None
    availability_status: AvailabilityStatus
    compliance: ComplianceResult
    current_assignment: EmployeeAssignmentRead | None
    current_project_id: uuid.UUID | None
    current_project_name: str | None
    current_location_id: uuid.UUID | None
    current_location_name: str | None
    current_rotation: EmployeeRotationRead | None
    primary_emergency_contact: EmployeeEmergencyContactRead | None
    emergency_contacts: list[EmployeeEmergencyContactRead]
    family_summary: FamilySummary
    current_resume: EmployeeResumeRead | None
    skills: list[EmployeeSkillRead]
    licenses: list[EmployeeLicenseRead]
    qualifications: list[EmployeeQualificationRead]
    recent_training: list[EmployeeTrainingRead]
    expiring_documents: list[EmployeeDocumentRead]
    expiring_licenses: list[EmployeeLicenseRead]
    expiring_training: list[EmployeeTrainingRead]
    recent_assignments: list[EmployeeAssignmentRead]
    asset_authorizations: list[EmployeeAssetAuthorizationRead]


class WorkforceDashboard(ORMModel):
    total_employees: int
    active_employees: int
    assigned_employees: int
    available_employees: int
    off_rotation: int
    on_leave: int
    suspended: int
    employees_by_department: dict[str, int]
    employees_by_position: dict[str, int]
    employees_by_project: dict[str, int]
    expiring_documents: int
    expired_documents: int
    expiring_licenses: int
    expired_licenses: int
    expiring_training: int
    contracts_expiring: int
    employees_without_emergency_contact: int
    employees_without_current_resume: int
    employees_missing_required_documents: int


class ManpowerGroup(ORMModel):
    key: str
    count: int


class ManpowerSummary(ORMModel):
    project_id: uuid.UUID
    total_assigned: int
    on_site: int
    off_rotation: int
    by_department: list[ManpowerGroup]
    by_position: list[ManpowerGroup]
    by_role: list[ManpowerGroup]
    by_rotation_status: list[ManpowerGroup]
    relief_staff: list[EmployeeBasic]


EmployeeFull.model_rebuild()
