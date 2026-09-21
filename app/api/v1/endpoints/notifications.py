"""Notification resolution, forwarding, and granular notification scheduling endpoints."""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import User
from app.schemas.hr import (
    NotificationForwardRequest,
    NotificationScheduleCreate,
    NotificationScheduleUpdate,
)
from app.services.notification_service import NotificationService

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    domain: str | None = Query(None),
    priority_tag: str | None = Query(None),
    is_resolved: bool | None = Query(None),
    is_read: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = Query(None),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    try:
        async with asyncio.timeout(5):
            items, total = await service.list_notifications(
                domain=domain,
                priority_tag=priority_tag,
                is_resolved=is_resolved,
                is_read=is_read,
                page=page,
                page_size=page_size,
                search=search,
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503, detail="Notification sync timed out; retry shortly.",
            headers={"Retry-After": "30"},
        ) from exc
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/notifications/unread-count")
async def unread_notification_count(
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    try:
        async with asyncio.timeout(5):
            total = await NotificationService(session, actor).unread_count()
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503, detail="Notification sync timed out; retry shortly.",
            headers={"Retry-After": "30"},
        ) from exc
    return {"total": total}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    return await service.mark_read(notification_id)


@router.post("/notifications/{notification_id}/resolve")
async def resolve_notification(
    notification_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    return await service.resolve_notification(notification_id)


@router.post("/notifications/{notification_id}/forward")
async def forward_notification(
    notification_id: uuid.UUID,
    body: NotificationForwardRequest,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    return await service.forward_notification(
        notification_id=notification_id,
        target_user_id=body.target_user_id,
        target_user_ids=body.target_user_ids,
        notes=body.notes,
    )


# ── Notification Schedules Endpoints ─────────────────────────────────────────


@router.get("/notification-schedules")
async def list_notification_schedules(
    domain: str | None = Query(None),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    rows = await service.list_schedules(domain=domain)
    return [
        {
            "id": r.id,
            "title": r.title,
            "domain": r.domain,
            "rule_type": r.rule_type,
            "lead_time_days": r.lead_time_days,
            "frequency": r.frequency,
            "priority_tag": r.priority_tag,
            "delivery_method": r.delivery_method,
            "recipient_user_ids": r.recipient_user_ids or [],
            "recipient_roles": r.recipient_roles or [],
            "is_active": r.is_active,
            "last_run_at": r.last_run_at,
            "next_run_at": r.next_run_at,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/notification-schedules", status_code=201)
async def create_notification_schedule(
    body: NotificationScheduleCreate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    row = await service.create_schedule(body.model_dump(exclude_unset=True))
    return {
        "id": row.id,
        "title": row.title,
        "domain": row.domain,
        "rule_type": row.rule_type,
        "lead_time_days": row.lead_time_days,
        "frequency": row.frequency,
        "priority_tag": row.priority_tag,
        "delivery_method": row.delivery_method,
        "recipient_user_ids": row.recipient_user_ids,
        "recipient_roles": row.recipient_roles,
        "is_active": row.is_active,
        "created_at": row.created_at,
    }


@router.get("/notification-schedules/{schedule_id}")
async def get_notification_schedule(
    schedule_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    schedules = await service.list_schedules()
    found = next((s for s in schedules if s.id == schedule_id), None)
    if not found:
        return {"error": "Schedule not found"}
    return {
        "id": found.id,
        "title": found.title,
        "domain": found.domain,
        "rule_type": found.rule_type,
        "lead_time_days": found.lead_time_days,
        "frequency": found.frequency,
        "priority_tag": found.priority_tag,
        "delivery_method": found.delivery_method,
        "recipient_user_ids": found.recipient_user_ids or [],
        "recipient_roles": found.recipient_roles or [],
        "is_active": found.is_active,
        "last_run_at": found.last_run_at,
        "next_run_at": found.next_run_at,
        "created_at": found.created_at,
    }


@router.patch("/notification-schedules/{schedule_id}")
@router.put("/notification-schedules/{schedule_id}")
async def update_notification_schedule(
    schedule_id: uuid.UUID,
    body: NotificationScheduleUpdate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    row = await service.update_schedule(schedule_id, body.model_dump(exclude_unset=True))
    return {
        "id": row.id,
        "title": row.title,
        "domain": row.domain,
        "rule_type": row.rule_type,
        "lead_time_days": row.lead_time_days,
        "frequency": row.frequency,
        "priority_tag": row.priority_tag,
        "delivery_method": row.delivery_method,
        "recipient_user_ids": row.recipient_user_ids or [],
        "recipient_roles": row.recipient_roles or [],
        "is_active": row.is_active,
        "last_run_at": row.last_run_at,
        "next_run_at": row.next_run_at,
        "created_at": row.created_at,
    }


@router.delete("/notification-schedules/{schedule_id}")
async def delete_notification_schedule(
    schedule_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    await service.delete_schedule(schedule_id)
    return {"status": "deleted"}


@router.post("/notification-schedules/{schedule_id}/run-now")
async def run_notification_schedule_now(
    schedule_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = NotificationService(session, actor)
    schedules = await service.list_schedules()
    found = next((s for s in schedules if s.id == schedule_id), None)
    if not found:
        return {"error": "Schedule not found"}

    generated = await service.evaluate_schedule(found)
    return {"status": "success", "generated_notifications": generated}
