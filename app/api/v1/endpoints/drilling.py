import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.drilling import ShiftReportStatus
from app.models.user import User
from app.schemas.drilling import (
    ApproveShiftReportRequest,
    DrillHoleCreate,
    DrillHoleResponse,
    DrillHoleUpdate,
    DrillingProgramCreate,
    DrillingProgramResponse,
    DrillingProgramUpdate,
    DrillingShiftReportCreate,
    DrillingShiftReportResponse,
    DrillingShiftReportUpdate,
    ProjectDrillingSummaryResponse,
    ReturnShiftReportRequest,
    SubmitShiftReportRequest,
)
from app.services import drilling as drilling_service

router = APIRouter(prefix="/drilling", tags=["drilling"])


# --- Drilling Programs ---
@router.post("/programs", response_model=DrillingProgramResponse, status_code=status.HTTP_201_CREATED)
async def create_drilling_program(
    payload: DrillingProgramCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.create_drilling_program(
            session=session,
            organization_id=user.organization_id,
            payload=payload,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/programs", response_model=list[DrillingProgramResponse])
async def list_drilling_programs(
    project_id: uuid.UUID | None = Query(None, description="Filter by Project ID"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    return await drilling_service.list_drilling_programs(
        session=session,
        organization_id=user.organization_id,
        project_id=project_id,
    )


@router.get("/programs/{program_id}", response_model=DrillingProgramResponse)
async def get_drilling_program(
    program_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    program = await drilling_service.get_drilling_program(
        session=session,
        organization_id=user.organization_id,
        program_id=program_id,
    )
    if not program:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drilling Program not found.")
    return program


@router.put("/programs/{program_id}", response_model=DrillingProgramResponse)
async def update_drilling_program(
    program_id: uuid.UUID,
    payload: DrillingProgramUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.update_drilling_program(
            session=session,
            organization_id=user.organization_id,
            program_id=program_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --- Drill Holes ---
@router.post("/holes", response_model=DrillHoleResponse, status_code=status.HTTP_201_CREATED)
async def create_drill_hole(
    payload: DrillHoleCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.create_drill_hole(
            session=session,
            organization_id=user.organization_id,
            payload=payload,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/holes", response_model=list[DrillHoleResponse])
async def list_drill_holes(
    project_id: uuid.UUID | None = Query(None, description="Filter by Project ID"),
    program_id: uuid.UUID | None = Query(None, description="Filter by Drilling Program ID"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    return await drilling_service.list_drill_holes(
        session=session,
        organization_id=user.organization_id,
        project_id=project_id,
        program_id=program_id,
    )


@router.get("/holes/{hole_id}", response_model=DrillHoleResponse)
async def get_drill_hole(
    hole_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    hole = await drilling_service.get_drill_hole(
        session=session,
        organization_id=user.organization_id,
        hole_id=hole_id,
    )
    if not hole:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drill Hole not found.")
    return hole


@router.put("/holes/{hole_id}", response_model=DrillHoleResponse)
async def update_drill_hole(
    hole_id: uuid.UUID,
    payload: DrillHoleUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.update_drill_hole(
            session=session,
            organization_id=user.organization_id,
            hole_id=hole_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --- Shift Reports ---
@router.post("/shifts", response_model=DrillingShiftReportResponse, status_code=status.HTTP_201_CREATED)
async def create_shift_report(
    payload: DrillingShiftReportCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.create_shift_report(
            session=session,
            organization_id=user.organization_id,
            payload=payload,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/shifts", response_model=list[DrillingShiftReportResponse])
async def list_shift_reports(
    project_id: uuid.UUID | None = Query(None, description="Filter by Project ID"),
    rig_id: uuid.UUID | None = Query(None, description="Filter by Rig Asset ID"),
    date_from: date | None = Query(None, description="Start date filter"),
    date_to: date | None = Query(None, description="End date filter"),
    shift_status: ShiftReportStatus | None = Query(None, alias="status", description="Filter by Shift Status"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    return await drilling_service.list_shift_reports(
        session=session,
        organization_id=user.organization_id,
        project_id=project_id,
        rig_id=rig_id,
        date_from=date_from,
        date_to=date_to,
        status=shift_status,
    )


@router.get("/shifts/{shift_id}", response_model=DrillingShiftReportResponse)
async def get_shift_report(
    shift_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    report = await drilling_service.get_shift_report(
        session=session,
        organization_id=user.organization_id,
        shift_id=shift_id,
    )
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift Report not found.")
    return report


@router.put("/shifts/{shift_id}", response_model=DrillingShiftReportResponse)
async def update_shift_report(
    shift_id: uuid.UUID,
    payload: DrillingShiftReportUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.update_shift_report(
            session=session,
            organization_id=user.organization_id,
            shift_id=shift_id,
            payload=payload,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --- Shift State Machine Endpoints ---
@router.post("/shifts/{shift_id}/submit", response_model=DrillingShiftReportResponse)
async def submit_shift_report(
    shift_id: uuid.UUID,
    payload: SubmitShiftReportRequest = SubmitShiftReportRequest(),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.submit_shift_report(
            session=session,
            organization_id=user.organization_id,
            shift_id=shift_id,
            user_id=user.id,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/shifts/{shift_id}/approve", response_model=DrillingShiftReportResponse)
async def approve_shift_report(
    shift_id: uuid.UUID,
    payload: ApproveShiftReportRequest = ApproveShiftReportRequest(),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.approve_shift_report(
            session=session,
            organization_id=user.organization_id,
            shift_id=shift_id,
            user_id=user.id,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/shifts/{shift_id}/return", response_model=DrillingShiftReportResponse)
async def return_shift_report(
    shift_id: uuid.UUID,
    payload: ReturnShiftReportRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    try:
        return await drilling_service.return_shift_report(
            session=session,
            organization_id=user.organization_id,
            shift_id=shift_id,
            user_id=user.id,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# --- Project Drilling Summary ---
@router.get("/projects/{project_id}/summary", response_model=ProjectDrillingSummaryResponse)
async def get_project_drilling_summary(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    return await drilling_service.get_project_drilling_summary(
        session=session,
        organization_id=user.organization_id,
        project_id=project_id,
    )
