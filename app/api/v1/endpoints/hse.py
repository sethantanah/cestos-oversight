import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.dependencies import get_current_user, request_storage
from app.db.session import get_session
from app.models.maintenance_hse import HseIncident, HseIncidentStatus
from app.models.user import User
from app.models.employee import Employee
from app.models.document_library import LibraryDocument
from app.schemas.maintenance_hse import (
    HseCorrectiveActionCreate,
    HseCorrectiveActionResponse,
    HseCorrectiveActionUpdate,
    HseIncidentCreate,
    HseIncidentResponse,
    HseIncidentUpdate,
)
from app.services import hse as hse_service

router = APIRouter(prefix="/hse", tags=["hse"])


@router.post("/incidents", response_model=HseIncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: HseIncidentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseIncidentResponse:
    employee_id = await session.scalar(select(Employee.id).where(
        Employee.organization_id == current_user.organization_id,
        Employee.user_id == current_user.id,
        Employee.archived_at.is_(None),
    ))
    if employee_id is None:
        raise HTTPException(status_code=422, detail="Your user account is not linked to an employee record, so an incident reporter cannot be assigned.")
    payload = payload.model_copy(update={"reported_by_id": employee_id})
    try:
        incident = await hse_service.create_incident(
            session, current_user.organization_id, payload, actor_id=current_user.id
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return HseIncidentResponse.model_validate(incident)


@router.get("/incidents", response_model=list[HseIncidentResponse])
async def list_incidents(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: uuid.UUID | None = Query(None),
    status: HseIncidentStatus | None = Query(None),
) -> list[HseIncidentResponse]:
    incidents = await hse_service.list_incidents(
        session, current_user.organization_id, project_id=project_id, status=status
    )
    return [HseIncidentResponse.model_validate(inc) for inc in incidents]


@router.get("/incidents/{incident_id}", response_model=HseIncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseIncidentResponse:
    incident = await hse_service.get_incident(
        session, current_user.organization_id, incident_id
    )
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found.")
    return HseIncidentResponse.model_validate(incident)


@router.patch("/incidents/{incident_id}", response_model=HseIncidentResponse)
async def update_incident(
    incident_id: uuid.UUID,
    payload: HseIncidentUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseIncidentResponse:
    try:
        incident = await hse_service.update_incident(
            session, current_user.organization_id, incident_id, payload, actor_id=current_user.id
        )
        return HseIncidentResponse.model_validate(incident)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/incidents/{incident_id}/actions", response_model=HseCorrectiveActionResponse, status_code=status.HTTP_201_CREATED)
async def add_action_to_incident(
    incident_id: uuid.UUID,
    payload: HseCorrectiveActionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseCorrectiveActionResponse:
    try:
        action = await hse_service.add_action_to_incident(
            session, current_user.organization_id, incident_id, payload, actor_id=current_user.id
        )
        return HseCorrectiveActionResponse.model_validate(action)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.patch("/actions/{action_id}", response_model=HseCorrectiveActionResponse)
async def update_action(
    action_id: uuid.UUID,
    payload: HseCorrectiveActionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HseCorrectiveActionResponse:
    try:
        action = await hse_service.update_action(
            session, current_user.organization_id, action_id, payload, actor_id=current_user.id
        )
        return HseCorrectiveActionResponse.model_validate(action)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


def _legacy_incident_payload(payload: dict, employee_id: uuid.UUID) -> HseIncidentCreate:
    incident_type = str(payload.get("incident_type") or "NEAR_MISS").upper()
    incident_type = {
        "INJURY_ILLNESS": "MEDICAL_TREATMENT",
        "ENVIRONMENTAL": "ENVIRONMENTAL_SPILL",
        "HAZARD_OBSERVATION": "NEAR_MISS",
        "SECURITY": "NEAR_MISS",
        "OTHER": "NEAR_MISS",
    }.get(incident_type, incident_type)
    occurred_at = payload.get("occurred_at") or payload.get("incident_date")
    if not occurred_at:
        raise HTTPException(status_code=422, detail="Incident date and time are required")
    notes = payload.get("notes")
    location = payload.get("location")
    if location:
        notes = "\n".join(filter(None, [notes, f"Specific location: {location}"]))
    employee_involved = payload.get("employee_id")
    if employee_involved:
        notes = "\n".join(filter(None, [notes, f"Employee involved: {employee_involved}"]))
    try:
        return HseIncidentCreate.model_validate({
            "title": payload.get("title"),
            "incident_type": incident_type,
            "severity": payload.get("severity") or "MEDIUM",
            "occurred_at": occurred_at,
            "project_id": payload.get("project_id"),
            "site_location_id": payload.get("site_location_id"),
            "asset_id": payload.get("asset_id"),
            "reported_by_id": employee_id,
            "description": payload.get("description"),
            "immediate_actions_taken": payload.get("immediate_actions_taken") or payload.get("corrective_action"),
            "notes": notes,
        })
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Check the incident type, project, date, title and description") from exc


def _legacy_incident_read(incident: HseIncidentResponse, attachments: list[dict] | None = None) -> dict:
    data = incident.model_dump(mode="json")
    data["incident_date"] = data.get("occurred_at")
    data["corrective_action"] = data.get("immediate_actions_taken")
    location_note = next((line.partition(":")[2].strip() for line in (data.get("notes") or "").splitlines() if line.lower().startswith("specific location:")), None)
    data["location"] = location_note
    data["attachments"] = attachments or []
    return data


async def _legacy_attachments(session: AsyncSession, organization_id: uuid.UUID, incidents: list[HseIncident]) -> dict[uuid.UUID, list[dict]]:
    if not incidents:
        return {}
    incident_ids = {str(incident.id) for incident in incidents}
    conditions = [LibraryDocument.tags.contains([incident_id]) for incident_id in incident_ids]
    documents = (await session.scalars(select(LibraryDocument).where(
        LibraryDocument.organization_id == organization_id,
        LibraryDocument.source_type == "hse_incident",
        LibraryDocument.visibility == "PUBLIC",
        LibraryDocument.is_active.is_(True),
        or_(*conditions),
    ))).all()
    grouped: dict[uuid.UUID, list[dict]] = {}
    for document in documents:
        incident_key = next((tag for tag in document.tags or [] if tag in incident_ids), None)
        if incident_key:
            grouped.setdefault(uuid.UUID(incident_key), []).append({
                "id": str(document.id), "document_id": str(document.id),
                "filename": document.file_name, "file_size": f"{document.size_bytes / 1024:.1f} KB",
            })
    return grouped


async def legacy_create_incident(
    request: Request,
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage=Depends(request_storage),
):
    """Compatibility endpoint for older portals using /api/v1/incidents."""
    employee_id = await session.scalar(select(Employee.id).where(
        Employee.organization_id == actor.organization_id,
        Employee.user_id == actor.id,
        Employee.archived_at.is_(None),
    ))
    if employee_id is None:
        raise HTTPException(status_code=422, detail="Your user account is not linked to an employee record")
    attachments = []
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload = dict(form)
        files = [value for value in form.getlist("files") if isinstance(value, StarletteUploadFile)]
    else:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Incident details are required") from exc
        files = []
    body = _legacy_incident_payload(payload, employee_id)
    try:
        incident = await hse_service.create_incident(session, actor.organization_id, body, actor_id=actor.id)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    for uploaded in files:
        try:
            data = await uploaded.read(storage.max_bytes + 1)
            if not data:
                continue
            stored = await run_in_threadpool(storage.save, f"documents/{actor.organization_id}/hse-incidents", data, uploaded.filename or "incident-evidence", uploaded.content_type)
            document_id = uuid.uuid4()
            doc = LibraryDocument(
                id=document_id,
                organization_id=actor.organization_id,
                source_type="hse_incident",
                source_id=uuid.uuid4(),
                title=f"HSE Incident {incident.incident_number} - {uploaded.filename or 'Evidence'}",
                category="HSE",
                tags=["hse_incident", str(incident.id)],
                storage_path=stored.relative_path,
                file_name=stored.filename,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                owner_id=actor.id,
                visibility="PUBLIC",
            )
            session.add(doc)
            attachments.append({"id": str(document_id), "document_id": str(document_id), "filename": doc.file_name, "file_size": f"{doc.size_bytes / 1024:.1f} KB"})
        except Exception:
            continue
    if attachments:
        await session.commit()
    response = HseIncidentResponse.model_validate(incident)
    return _legacy_incident_read(response, attachments)


async def legacy_list_incidents(
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: uuid.UUID | None = Query(None),
    status_value: HseIncidentStatus | None = Query(None, alias="status"),
):
    incidents = await hse_service.list_incidents(session, actor.organization_id, project_id=project_id, status=status_value)
    attachments = await _legacy_attachments(session, actor.organization_id, incidents)
    return [_legacy_incident_read(HseIncidentResponse.model_validate(incident), attachments.get(incident.id)) for incident in incidents]


async def legacy_get_incident(
    incident_id: uuid.UUID,
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    incident = await hse_service.get_incident(session, actor.organization_id, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    attachments = await _legacy_attachments(session, actor.organization_id, [incident])
    return _legacy_incident_read(HseIncidentResponse.model_validate(incident), attachments.get(incident.id))


async def legacy_update_incident(
    incident_id: uuid.UUID,
    payload: HseIncidentUpdate,
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        incident = await hse_service.update_incident(session, actor.organization_id, incident_id, payload, actor_id=actor.id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return _legacy_incident_read(HseIncidentResponse.model_validate(incident))
