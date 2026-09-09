import uuid
from collections.abc import Sequence
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import request_storage, require_permission
from app.core.storage import LocalStorage
from app.db.session import get_session
from app.models import User
from app.models.employee import (
    AvailabilityStatus,
    DocumentType,
    EmploymentStatus,
    EmploymentType,
    RotationStatus,
)
from app.schemas.common import Page
from app.schemas.employee import (
    ActivityEntry,
    AssetAuthorizationCreate,
    AssetAuthorizationUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DocumentExpiringRead,
    EmergencyContactCreate,
    EmergencyContactUpdate,
    EmployeeAssetAuthorizationRead,
    EmployeeAssignmentCreate,
    EmployeeAssignmentRead,
    EmployeeAssignmentUpdate,
    EmployeeBasic,
    EmployeeCreate,
    EmployeeDocumentCreate,
    EmployeeDocumentRead,
    EmployeeDocumentUpdate,
    EmployeeEmergencyContactRead,
    EmployeeFamilyCreate,
    EmployeeFamilyRead,
    EmployeeFamilyUpdate,
    EmployeeFull,
    EmployeeLicenseRead,
    EmployeeOverview,
    EmployeeQualificationRead,
    EmployeeRead,
    EmployeeResumeCreate,
    EmployeeResumeRead,
    EmployeeResumeUpdate,
    EmployeeRotationCreate,
    EmployeeRotationRead,
    EmployeeSkillCreate,
    EmployeeSkillRead,
    EmployeeSkillUpdate,
    EmployeeTrainingRead,
    EmployeeTransferRequest,
    EmployeeUpdate,
    LeaveRequestCreate,
    LeaveRequestRead,
    LeaveRequestUpdate,
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
    TimeLogCreate,
    TimeLogRead,
    TrainingCreate,
    TrainingExpiringRead,
    TrainingUpdate,
    WorkforceDashboard,
)
from app.services.employees import EmployeeService
from app.services.workforce import (
    AuthorizationService,
    DepartmentService,
    DocumentService,
    EmergencyContactService,
    FamilyService,
    LicenseService,
    PositionService,
    QualificationService,
    ResumeService,
    RotationService,
    SkillService,
    TrainingService,
    TimeLogService,
    LeaveRequestService,
)

router = APIRouter(prefix="/employees", tags=["employees"])
assignments_router = APIRouter(prefix="/employee-assignments", tags=["assignments"])
family_router = APIRouter(prefix="/employee-family-members", tags=["family"])
emergency_router = APIRouter(prefix="/employee-emergency-contacts", tags=["emergency-contacts"])
resumes_router = APIRouter(prefix="/employee-resumes", tags=["resumes"])
documents_router = APIRouter(prefix="/employee-documents", tags=["documents"])
qualifications_router = APIRouter(prefix="/employee-qualifications", tags=["qualifications"])
skills_router = APIRouter(prefix="/skills", tags=["skills"])
employee_skills_router = APIRouter(prefix="/employee-skills", tags=["skills"])
training_router = APIRouter(prefix="/employee-training", tags=["training"])
training_global_router = APIRouter(prefix="/training", tags=["training"])
licenses_router = APIRouter(prefix="/employee-licenses", tags=["licenses"])
licenses_global_router = APIRouter(prefix="/employee-licenses", tags=["licenses"])
patterns_router = APIRouter(prefix="/rotation-patterns", tags=["rotations"])
rotations_router = APIRouter(prefix="/rotations", tags=["rotations"])
authorizations_router = APIRouter(prefix="/employee-asset-authorizations", tags=["authorizations"])
departments_router = APIRouter(prefix="/departments", tags=["departments"])
positions_router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=Page[EmployeeRead])
async def list_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    department: str | None = None,
    department_id: uuid.UUID | None = None,
    position_id: uuid.UUID | None = None,
    employment_type: EmploymentType | None = None,
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
    document_expiring_within_days: int | None = Query(None, ge=1, le=365),
    contract_expiring_within_days: int | None = Query(None, ge=1, le=365),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> Page[EmployeeRead]:
    return await EmployeeService(session, actor).list(
        page,
        page_size,
        search,
        department,
        department_id,
        position_id,
        employment_type.value if employment_type else None,
        employment_status,
        availability_status,
        job_title,
        project_id,
        location_id,
        supervisor_id,
        skill_id,
        license_type,
        rotation_status,
        is_active,
        unassigned_only,
        document_expiring_within_days,
        contract_expiring_within_days,
        sort_by,
        sort_dir,
    )


@router.post("", response_model=EmployeeRead, status_code=201)
async def create_employee(
    body: EmployeeCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.create")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    return await EmployeeService(session, actor).create(body, request)


@router.get("/available", response_model=Page[EmployeeBasic])
async def available_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    position_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    skill_id: uuid.UUID | None = None,
    license_type: str | None = None,
    asset_category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> Page[EmployeeBasic]:
    return await EmployeeService(session, actor).available(
        page,
        page_size,
        position_id,
        department_id,
        skill_id,
        license_type,
        asset_category_id,
        project_id,
    )


@router.get("/dashboard-summary", response_model=WorkforceDashboard)
async def workforce_dashboard(
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> WorkforceDashboard:
    return await EmployeeService(session, actor).dashboard()


@router.get("/{employee_id}", response_model=EmployeeRead)
async def get_employee(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    return await EmployeeService(session, actor).get(employee_id)


@router.get("/{employee_id}/full", response_model=EmployeeFull)
async def get_employee_full(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.read_full")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeFull:
    return await EmployeeService(session, actor).get_full(employee_id)


@router.patch("/{employee_id}", response_model=EmployeeRead)
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.update")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    return await EmployeeService(session, actor).update(employee_id, body, request)


@router.post("/{employee_id}/archive", response_model=EmployeeRead)
async def archive_employee(
    employee_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.archive")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    return await EmployeeService(session, actor).archive(employee_id, request)


@router.post("/{employee_id}/restore", response_model=EmployeeRead)
async def restore_employee(
    employee_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.archive")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    return await EmployeeService(session, actor).restore(employee_id, request)


@router.get("/{employee_id}/overview", response_model=EmployeeOverview)
async def employee_overview(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.read_full")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeOverview:
    return await EmployeeService(session, actor).overview(employee_id)


@router.get("/{employee_id}/activity", response_model=list[ActivityEntry])
async def employee_activity(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.audit.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[ActivityEntry]:
    return await EmployeeService(session, actor).activity(employee_id)


@router.post("/{employee_id}/transfer", response_model=EmployeeAssignmentRead, status_code=201)
async def transfer_employee(
    employee_id: uuid.UUID,
    body: EmployeeTransferRequest,
    request: Request,
    actor: User = Depends(require_permission("employees.transfer")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssignmentRead:
    return await EmployeeService(session, actor).transfer(employee_id, body, request)


@router.get("/{employee_id}/assignments", response_model=list[EmployeeAssignmentRead])
async def list_employee_assignments(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeAssignmentRead]:
    return await EmployeeService(session, actor).list_assignments(employee_id)


@router.post("/{employee_id}/assignments", response_model=EmployeeAssignmentRead, status_code=201)
async def create_employee_assignment(
    employee_id: uuid.UUID,
    body: EmployeeAssignmentCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.assign")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssignmentRead:
    return await EmployeeService(session, actor).create_assignment(employee_id, body, request)


@assignments_router.get("/{assignment_id}", response_model=EmployeeAssignmentRead)
async def get_employee_assignment(
    assignment_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssignmentRead:
    return await EmployeeService(session, actor).get_assignment(assignment_id)


@assignments_router.patch("/{assignment_id}", response_model=EmployeeAssignmentRead)
async def update_employee_assignment(
    assignment_id: uuid.UUID,
    body: EmployeeAssignmentUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.assign")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssignmentRead:
    return await EmployeeService(session, actor).update_assignment(assignment_id, body, request)


@assignments_router.post("/{assignment_id}/complete", response_model=EmployeeAssignmentRead)
async def complete_employee_assignment(
    assignment_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.assign")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssignmentRead:
    return await EmployeeService(session, actor).complete_assignment(assignment_id, request)


@assignments_router.post("/{assignment_id}/cancel", response_model=EmployeeAssignmentRead)
async def cancel_employee_assignment(
    assignment_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.assign")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssignmentRead:
    return await EmployeeService(session, actor).cancel_assignment(assignment_id, request)


@departments_router.get("", response_model=list[DepartmentRead])
async def list_departments(
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[DepartmentRead]:
    return await DepartmentService(session, actor).list()


@departments_router.post("", response_model=DepartmentRead, status_code=201)
async def create_department(
    body: DepartmentCreate,
    actor: User = Depends(require_permission("employees.update")),
    session: AsyncSession = Depends(get_session),
) -> DepartmentRead:
    return await DepartmentService(session, actor).create(body)


@departments_router.patch("/{department_id}", response_model=DepartmentRead)
async def update_department(
    department_id: uuid.UUID,
    body: DepartmentUpdate,
    actor: User = Depends(require_permission("employees.update")),
    session: AsyncSession = Depends(get_session),
) -> DepartmentRead:
    return await DepartmentService(session, actor).update(department_id, body)


@positions_router.get("", response_model=list[PositionRead])
async def list_positions(
    actor: User = Depends(require_permission("employees.read_basic")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[PositionRead]:
    return await PositionService(session, actor).list()


@positions_router.post("", response_model=PositionRead, status_code=201)
async def create_position(
    body: PositionCreate,
    actor: User = Depends(require_permission("employees.update")),
    session: AsyncSession = Depends(get_session),
) -> PositionRead:
    return await PositionService(session, actor).create(body)


@positions_router.patch("/{position_id}", response_model=PositionRead)
async def update_position(
    position_id: uuid.UUID,
    body: PositionUpdate,
    actor: User = Depends(require_permission("employees.update")),
    session: AsyncSession = Depends(get_session),
) -> PositionRead:
    return await PositionService(session, actor).update(position_id, body)


@router.get("/{employee_id}/family", response_model=list[EmployeeFamilyRead])
async def list_family(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.family.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeFamilyRead]:
    return await FamilyService(session, actor).list(employee_id)


@router.post("/{employee_id}/family", response_model=EmployeeFamilyRead, status_code=201)
async def add_family_member(
    employee_id: uuid.UUID,
    body: EmployeeFamilyCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.family.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeFamilyRead:
    return await FamilyService(session, actor).create(employee_id, body, request)


@family_router.get("/{member_id}", response_model=EmployeeFamilyRead)
async def get_family_member(
    member_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.family.read")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeFamilyRead:
    return await FamilyService(session, actor).get(member_id)


@family_router.patch("/{member_id}", response_model=EmployeeFamilyRead)
async def update_family_member(
    member_id: uuid.UUID,
    body: EmployeeFamilyUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.family.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeFamilyRead:
    return await FamilyService(session, actor).update(member_id, body, request)


@family_router.post("/{member_id}/archive", response_model=EmployeeFamilyRead)
async def archive_family_member(
    member_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.family.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeFamilyRead:
    return await FamilyService(session, actor).archive(member_id, request)


@family_router.post("/{member_id}/set-next-of-kin", response_model=EmployeeFamilyRead)
async def set_next_of_kin(
    member_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.family.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeFamilyRead:
    return await FamilyService(session, actor).set_next_of_kin(member_id, request)


@family_router.post("/{member_id}/set-dependent", response_model=EmployeeFamilyRead)
async def set_dependent(
    member_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.family.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeFamilyRead:
    return await FamilyService(session, actor).set_dependent(member_id, True, request)


@router.get("/{employee_id}/emergency-contacts", response_model=list[EmployeeEmergencyContactRead])
async def list_emergency_contacts(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.emergency_contacts.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeEmergencyContactRead]:
    return await EmergencyContactService(session, actor).list(employee_id)


@router.get("/{employee_id}/emergency-contact", response_model=EmployeeEmergencyContactRead)
async def primary_emergency_contact(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.emergency_contacts.read")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeEmergencyContactRead:
    return await EmergencyContactService(session, actor).primary(employee_id)


@router.post(
    "/{employee_id}/emergency-contacts",
    response_model=EmployeeEmergencyContactRead,
    status_code=201,
)
async def add_emergency_contact(
    employee_id: uuid.UUID,
    body: EmergencyContactCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.emergency_contacts.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeEmergencyContactRead:
    return await EmergencyContactService(session, actor).create(employee_id, body, request)


@emergency_router.get("/{contact_id}", response_model=EmployeeEmergencyContactRead)
async def get_emergency_contact(
    contact_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.emergency_contacts.read")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeEmergencyContactRead:
    return await EmergencyContactService(session, actor).get(contact_id)


@emergency_router.patch("/{contact_id}", response_model=EmployeeEmergencyContactRead)
async def update_emergency_contact(
    contact_id: uuid.UUID,
    body: EmergencyContactUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.emergency_contacts.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeEmergencyContactRead:
    return await EmergencyContactService(session, actor).update(contact_id, body, request)


@emergency_router.post("/{contact_id}/set-primary", response_model=EmployeeEmergencyContactRead)
async def set_primary_contact(
    contact_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.emergency_contacts.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeEmergencyContactRead:
    return await EmergencyContactService(session, actor).set_primary(contact_id, request)


@emergency_router.post("/{contact_id}/archive", response_model=EmployeeEmergencyContactRead)
async def archive_emergency_contact(
    contact_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.emergency_contacts.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeEmergencyContactRead:
    return await EmergencyContactService(session, actor).archive(contact_id, request)


@router.get("/{employee_id}/resumes", response_model=list[EmployeeResumeRead])
async def list_resumes(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.resume.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeResumeRead]:
    return await ResumeService(session, actor).list(employee_id)


@router.get("/{employee_id}/resume/current", response_model=EmployeeResumeRead)
async def current_resume(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.resume.read")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResumeRead:
    return await ResumeService(session, actor).current(employee_id)


@router.post("/{employee_id}/resumes", response_model=EmployeeResumeRead, status_code=201)
async def add_resume(
    employee_id: uuid.UUID,
    body: EmployeeResumeCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.resume.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResumeRead:
    return await ResumeService(session, actor).add(
        employee_id, body, None, None, None, None, request
    )


@router.post("/{employee_id}/resumes/upload", response_model=EmployeeResumeRead, status_code=201)
async def upload_resume(
    employee_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    notes: str | None = Form(None),
    actor: User = Depends(require_permission("employees.resume.manage")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> EmployeeResumeRead:
    data = await file.read()
    body = EmployeeResumeCreate(
        title=title or file.filename or "Resume",
        file_url="upload",
        file_name=file.filename,
        mime_type=file.content_type,
        file_size=len(data),
        notes=notes,
    )
    return await ResumeService(session, actor).add(
        employee_id, body, storage, data, file.filename, file.content_type, request
    )


@router.get("/{employee_id}/resumes/{resume_id}/download")
async def download_resume(
    employee_id: uuid.UUID,
    resume_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.resume.read")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> FileResponse:
    path, media_type, filename = await ResumeService(session, actor).download(
        employee_id, resume_id, storage
    )
    return FileResponse(path, media_type=media_type, filename=filename)


@resumes_router.patch("/{resume_id}", response_model=EmployeeResumeRead)
async def update_resume(
    resume_id: uuid.UUID,
    body: EmployeeResumeUpdate,
    actor: User = Depends(require_permission("employees.resume.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResumeRead:
    return await ResumeService(session, actor).update(resume_id, body.title, body.notes)


@resumes_router.post("/{resume_id}/set-current", response_model=EmployeeResumeRead)
async def set_current_resume(
    resume_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.resume.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResumeRead:
    return await ResumeService(session, actor).set_current(resume_id, request)


@resumes_router.post("/{resume_id}/archive", response_model=EmployeeResumeRead)
async def archive_resume(
    resume_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.resume.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResumeRead:
    return await ResumeService(session, actor).archive(resume_id, request)


@router.get("/{employee_id}/documents", response_model=list[EmployeeDocumentRead])
async def list_employee_documents(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.documents.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeDocumentRead]:
    return await DocumentService(session, actor).list(employee_id)


@router.post("/{employee_id}/documents", response_model=EmployeeDocumentRead, status_code=201)
async def add_employee_document(
    employee_id: uuid.UUID,
    body: EmployeeDocumentCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.documents.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeDocumentRead:
    return await DocumentService(session, actor).add(employee_id, body, request)


@router.post(
    "/{employee_id}/documents/upload", response_model=EmployeeDocumentRead, status_code=201
)
async def upload_employee_document(
    employee_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(DocumentType.OTHER),
    title: str | None = Form(None),
    document_number: str | None = Form(None),
    issue_date: date | None = Form(None),
    expiry_date: date | None = Form(None),
    issuing_authority: str | None = Form(None),
    notes: str | None = Form(None),
    actor: User = Depends(require_permission("employees.documents.manage")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> EmployeeDocumentRead:
    data = await file.read()
    return await DocumentService(session, actor).upload(
        employee_id,
        data,
        file.filename,
        file.content_type,
        storage,
        document_type,
        title,
        document_number,
        issue_date,
        expiry_date,
        issuing_authority,
        notes,
        request,
    )


@router.get("/{employee_id}/documents/{document_id}/download")
async def download_employee_document(
    employee_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.documents.read")),
    session: AsyncSession = Depends(get_session),
    storage: LocalStorage = Depends(request_storage),
) -> FileResponse:
    path, media_type, filename = await DocumentService(session, actor).download(
        employee_id, document_id, storage
    )
    return FileResponse(path, media_type=media_type, filename=filename)


@documents_router.get("/expiring", response_model=list[DocumentExpiringRead])
async def expiring_documents(
    days: int = Query(30, ge=1, le=365),
    actor: User = Depends(require_permission("employees.documents.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[DocumentExpiringRead]:
    return await DocumentService(session, actor).expiring(days)


@documents_router.get("/{document_id}", response_model=EmployeeDocumentRead)
async def get_employee_document(
    document_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.documents.read")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeDocumentRead:
    return await DocumentService(session, actor).get(document_id)


@documents_router.patch("/{document_id}", response_model=EmployeeDocumentRead)
async def update_employee_document(
    document_id: uuid.UUID,
    body: EmployeeDocumentUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.documents.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeDocumentRead:
    return await DocumentService(session, actor).update(document_id, body, request)


@documents_router.post("/{document_id}/verify", response_model=EmployeeDocumentRead)
async def verify_employee_document(
    document_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.documents.verify")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeDocumentRead:
    return await DocumentService(session, actor).verify(document_id, request)


@documents_router.post("/{document_id}/reject", response_model=EmployeeDocumentRead)
async def reject_employee_document(
    document_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.documents.verify")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeDocumentRead:
    return await DocumentService(session, actor).reject(document_id, request)


@documents_router.post("/{document_id}/archive", response_model=EmployeeDocumentRead)
async def archive_employee_document(
    document_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.documents.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeDocumentRead:
    return await DocumentService(session, actor).archive(document_id, request)


@router.get("/{employee_id}/qualifications", response_model=list[EmployeeQualificationRead])
async def list_qualifications(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.qualifications.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeQualificationRead]:
    return await QualificationService(session, actor).list(employee_id)


@router.post(
    "/{employee_id}/qualifications", response_model=EmployeeQualificationRead, status_code=201
)
async def add_qualification(
    employee_id: uuid.UUID,
    body: QualificationCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.qualifications.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeQualificationRead:
    return await QualificationService(session, actor).create(employee_id, body, request)


@qualifications_router.patch("/{qualification_id}", response_model=EmployeeQualificationRead)
async def update_qualification(
    qualification_id: uuid.UUID,
    body: QualificationUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.qualifications.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeQualificationRead:
    return await QualificationService(session, actor).update(qualification_id, body, request)


@qualifications_router.post("/{qualification_id}/archive", response_model=EmployeeQualificationRead)
async def archive_qualification(
    qualification_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.qualifications.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeQualificationRead:
    return await QualificationService(session, actor).archive(qualification_id, request)


@skills_router.get("", response_model=list[SkillRead])
async def list_skills(
    actor: User = Depends(require_permission("employees.skills.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[SkillRead]:
    return await SkillService(session, actor).list_all()


@skills_router.post("", response_model=SkillRead, status_code=201)
async def create_skill(
    body: SkillCreate,
    actor: User = Depends(require_permission("employees.skills.manage")),
    session: AsyncSession = Depends(get_session),
) -> SkillRead:
    return await SkillService(session, actor).create(body)


@skills_router.patch("/{skill_id}", response_model=SkillRead)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    actor: User = Depends(require_permission("employees.skills.manage")),
    session: AsyncSession = Depends(get_session),
) -> SkillRead:
    return await SkillService(session, actor).update(skill_id, body)


@router.get("/{employee_id}/skills", response_model=list[EmployeeSkillRead])
async def list_employee_skills(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.skills.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeSkillRead]:
    return await SkillService(session, actor).list_for_employee(employee_id)


@router.post("/{employee_id}/skills", response_model=EmployeeSkillRead, status_code=201)
async def assign_employee_skill(
    employee_id: uuid.UUID,
    body: EmployeeSkillCreate,
    actor: User = Depends(require_permission("employees.skills.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeSkillRead:
    return await SkillService(session, actor).assign(employee_id, body)


@employee_skills_router.patch("/{link_id}", response_model=EmployeeSkillRead)
async def update_employee_skill(
    link_id: uuid.UUID,
    body: EmployeeSkillUpdate,
    actor: User = Depends(require_permission("employees.skills.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeSkillRead:
    return await SkillService(session, actor).update_link(link_id, body)


@employee_skills_router.delete("/{link_id}", status_code=204)
async def remove_employee_skill(
    link_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.skills.manage")),
    session: AsyncSession = Depends(get_session),
) -> None:
    await SkillService(session, actor).unlink(link_id)


@router.get("/{employee_id}/training", response_model=list[EmployeeTrainingRead])
async def list_training(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.training.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeTrainingRead]:
    return await TrainingService(session, actor).list(employee_id)


@router.post("/{employee_id}/training", response_model=EmployeeTrainingRead, status_code=201)
async def add_training(
    employee_id: uuid.UUID,
    body: TrainingCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.training.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeTrainingRead:
    return await TrainingService(session, actor).create(employee_id, body, request)


@training_router.patch("/{training_id}", response_model=EmployeeTrainingRead)
async def update_training(
    training_id: uuid.UUID,
    body: TrainingUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.training.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeTrainingRead:
    return await TrainingService(session, actor).update(training_id, body, request)


@training_global_router.get("/expiring", response_model=list[TrainingExpiringRead])
async def expiring_training(
    days: int = Query(30, ge=1, le=365),
    actor: User = Depends(require_permission("employees.training.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[TrainingExpiringRead]:
    return await TrainingService(session, actor).expiring(days)


@training_global_router.get("/compliance", response_model=list[TrainingExpiringRead])
async def training_compliance(
    days: int = Query(30, ge=1, le=365),
    actor: User = Depends(require_permission("employees.training.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[TrainingExpiringRead]:
    return await TrainingService(session, actor).compliance(days)


@router.get("/{employee_id}/licenses", response_model=list[EmployeeLicenseRead])
async def list_licenses(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.licenses.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeLicenseRead]:
    return await LicenseService(session, actor).list(employee_id)


@router.post("/{employee_id}/licenses", response_model=EmployeeLicenseRead, status_code=201)
async def add_license(
    employee_id: uuid.UUID,
    body: LicenseCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.licenses.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeLicenseRead:
    return await LicenseService(session, actor).create(employee_id, body, request)


@licenses_router.patch("/{license_id}", response_model=EmployeeLicenseRead)
async def update_license(
    license_id: uuid.UUID,
    body: LicenseUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.licenses.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeLicenseRead:
    return await LicenseService(session, actor).update(license_id, body, request)


@licenses_global_router.get("/expiring", response_model=list[LicenseExpiringRead])
async def expiring_licenses(
    days: int = Query(30, ge=1, le=365),
    actor: User = Depends(require_permission("employees.licenses.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[LicenseExpiringRead]:
    return await LicenseService(session, actor).expiring(days)


@patterns_router.get("", response_model=list[RotationPatternRead])
async def list_rotation_patterns(
    actor: User = Depends(require_permission("employees.rotations.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[RotationPatternRead]:
    return await RotationService(session, actor).list_patterns()


@patterns_router.post("", response_model=RotationPatternRead, status_code=201)
async def create_rotation_pattern(
    body: RotationPatternCreate,
    actor: User = Depends(require_permission("employees.rotations.manage")),
    session: AsyncSession = Depends(get_session),
) -> RotationPatternRead:
    return await RotationService(session, actor).create_pattern(body)


@patterns_router.patch("/{pattern_id}", response_model=RotationPatternRead)
async def update_rotation_pattern(
    pattern_id: uuid.UUID,
    body: RotationPatternUpdate,
    actor: User = Depends(require_permission("employees.rotations.manage")),
    session: AsyncSession = Depends(get_session),
) -> RotationPatternRead:
    return await RotationService(session, actor).update_pattern(pattern_id, body)


@router.get("/{employee_id}/rotations", response_model=list[EmployeeRotationRead])
async def list_rotations(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.rotations.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeRotationRead]:
    return await RotationService(session, actor).list_rotations(employee_id)


@router.post("/{employee_id}/rotations", response_model=EmployeeRotationRead, status_code=201)
async def create_rotation(
    employee_id: uuid.UUID,
    body: EmployeeRotationCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.rotations.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRotationRead:
    return await RotationService(session, actor).create_rotation(employee_id, body, request)


@rotations_router.get("/current", response_model=list[EmployeeRotationRead])
async def current_rotations(
    project_id: uuid.UUID | None = None,
    actor: User = Depends(require_permission("employees.rotations.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeRotationRead]:
    return await RotationService(session, actor).current(project_id)


@rotations_router.get("/upcoming", response_model=list[EmployeeRotationRead])
async def upcoming_rotations(
    days: int = Query(14, ge=1, le=90),
    project_id: uuid.UUID | None = None,
    actor: User = Depends(require_permission("employees.rotations.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeRotationRead]:
    return await RotationService(session, actor).upcoming(days, project_id)


@router.get(
    "/{employee_id}/asset-authorizations",
    response_model=list[EmployeeAssetAuthorizationRead],
)
async def list_authorizations(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.asset_authorizations.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeAssetAuthorizationRead]:
    return await AuthorizationService(session, actor).list(employee_id)


@router.post(
    "/{employee_id}/asset-authorizations",
    response_model=EmployeeAssetAuthorizationRead,
    status_code=201,
)
async def add_authorization(
    employee_id: uuid.UUID,
    body: AssetAuthorizationCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.asset_authorizations.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssetAuthorizationRead:
    return await AuthorizationService(session, actor).create(employee_id, body, request)


@authorizations_router.patch("/{authorization_id}", response_model=EmployeeAssetAuthorizationRead)
async def update_authorization(
    authorization_id: uuid.UUID,
    body: AssetAuthorizationUpdate,
    request: Request,
    actor: User = Depends(require_permission("employees.asset_authorizations.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssetAuthorizationRead:
    return await AuthorizationService(session, actor).update(authorization_id, body, request)


@authorizations_router.post(
    "/{authorization_id}/revoke", response_model=EmployeeAssetAuthorizationRead
)
async def revoke_authorization(
    authorization_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.asset_authorizations.manage")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeAssetAuthorizationRead:
    return await AuthorizationService(session, actor).revoke(authorization_id, request)


@router.post("/{employee_id}/time-logs", response_model=TimeLogRead, status_code=201)
async def create_time_log(
    employee_id: uuid.UUID,
    body: TimeLogCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.time_log.create")),
    session: AsyncSession = Depends(get_session),
) -> TimeLogRead:
    return await TimeLogService(session, actor).create(employee_id, body, request)


@router.get("/{employee_id}/time-logs", response_model=list[TimeLogRead])
async def list_time_logs(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.time_log.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[TimeLogRead]:
    return await TimeLogService(session, actor).list(employee_id)


@router.post("/{employee_id}/leave-requests", response_model=LeaveRequestRead, status_code=201)
async def create_leave_request(
    employee_id: uuid.UUID,
    body: LeaveRequestCreate,
    request: Request,
    actor: User = Depends(require_permission("employees.leave.create")),
    session: AsyncSession = Depends(get_session),
) -> LeaveRequestRead:
    return await LeaveRequestService(session, actor).create(employee_id, body, request)


@router.get("/{employee_id}/leave-requests", response_model=list[LeaveRequestRead])
async def list_leave_requests(
    employee_id: uuid.UUID,
    actor: User = Depends(require_permission("employees.leave.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[LeaveRequestRead]:
    return await LeaveRequestService(session, actor).list(employee_id)


@router.patch("/{leave_request_id}/approve", response_model=LeaveRequestRead)
async def approve_leave_request(
    leave_request_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.leave.approve")),
    session: AsyncSession = Depends(get_session),
) -> LeaveRequestRead:
    leave = await LeaveRequestService(session, actor).update(
        leave_request_id,
        LeaveRequestUpdate(status="APPROVED"),
        request,
    )
    return leave


@router.patch("/{leave_request_id}/reject", response_model=LeaveRequestRead)
async def reject_leave_request(
    leave_request_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("employees.leave.reject")),
    session: AsyncSession = Depends(get_session),
) -> LeaveRequestRead:
    leave = await LeaveRequestService(session, actor).update(
        leave_request_id,
        LeaveRequestUpdate(status="REJECTED"),
        request,
    )
    return leave
