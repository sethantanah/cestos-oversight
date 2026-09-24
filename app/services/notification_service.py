"""Service for managing notifications, resolution, forwarding, and automated schedule evaluation."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models import Employee, User
from app.models.hr import (
    EmailDelivery,
    Notification,
    NotificationSchedule,
)


class NotificationService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    async def list_notifications(
        self,
        domain: str | None = None,
        priority_tag: str | None = None,
        is_resolved: bool | None = None,
        is_read: bool | None = None,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = (
            select(Notification)
            .where(
                Notification.organization_id == self.actor.organization_id,
                Notification.recipient_id == self.actor.id,
                Notification.delivery_method.in_(["BOTH", "ON_PLATFORM"]),
            )
            .order_by(Notification.created_at.desc())
        )

        if domain:
            stmt = stmt.where(Notification.domain == domain.upper())
        if priority_tag:
            stmt = stmt.where(Notification.priority_tag == priority_tag.upper())
        if is_resolved is not None:
            stmt = stmt.where(Notification.is_resolved.is_(is_resolved))
        if is_read is not None:
            if is_read:
                stmt = stmt.where(Notification.read_at.is_not(None))
            else:
                stmt = stmt.where(Notification.read_at.is_(None))

        if search:
            stmt = stmt.where(Notification.message.icontains(search, autoescape=True))

        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ) or 0
        paged = (await self.session.scalars(
            stmt.order_by(Notification.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).all()

        # Fetch names for users
        user_ids = set()
        for r in paged:
            if r.recipient_id:
                user_ids.add(r.recipient_id)
            if r.resolved_by_id:
                user_ids.add(r.resolved_by_id)
            if r.forwarded_from_id:
                user_ids.add(r.forwarded_from_id)
            if r.forwarded_to_id:
                user_ids.add(r.forwarded_to_id)

        user_map: dict[uuid.UUID, str] = {}
        if user_ids:
            users = (
                await self.session.scalars(
                    select(User).where(
                        User.id.in_(user_ids),
                        User.organization_id == self.actor.organization_id,
                    )
                )
            ).all()
            for u in users:
                user_map[u.id] = u.email or str(u.id)

        result = []
        for r in paged:
            result.append(
                {
                    "id": r.id,
                    "message": r.message,
                    "action_url": r.action_url,
                    "domain": r.domain,
                    "priority_tag": r.priority_tag,
                    "delivery_method": r.delivery_method,
                    "created_at": r.created_at,
                    "read_at": r.read_at,
                    "is_resolved": r.is_resolved,
                    "resolved_at": r.resolved_at,
                    "resolved_by_id": r.resolved_by_id,
                    "resolved_by_name": user_map.get(r.resolved_by_id, ""),
                    "recipient_id": r.recipient_id,
                    "recipient_name": user_map.get(r.recipient_id, ""),
                    "forwarded_from_id": r.forwarded_from_id,
                    "forwarded_from_name": user_map.get(r.forwarded_from_id, ""),
                    "forwarded_to_id": r.forwarded_to_id,
                    "forwarded_to_name": user_map.get(r.forwarded_to_id, ""),
                    "forwarded_at": r.forwarded_at,
                    "forward_notes": r.forward_notes,
                }
            )

        return result, total

    async def unread_count(self) -> int:
        return await self.session.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.organization_id == self.actor.organization_id,
                Notification.recipient_id == self.actor.id,
                Notification.delivery_method.in_(["BOTH", "ON_PLATFORM"]),
                Notification.read_at.is_(None),
            )
        ) or 0

    async def mark_read(self, notification_id: uuid.UUID) -> dict[str, Any]:
        row = await self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.organization_id == self.actor.organization_id,
                Notification.recipient_id == self.actor.id,
            )
        )
        if not row:
            raise NotFoundError("Notification not found")

        row.read_at = datetime.now(UTC)
        await self.session.commit()
        return {"id": row.id, "read_at": row.read_at}

    async def resolve_notification(self, notification_id: uuid.UUID) -> dict[str, Any]:
        row = await self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.organization_id == self.actor.organization_id,
                Notification.recipient_id == self.actor.id,
            )
        )
        if not row:
            raise NotFoundError("Notification not found")

        row.is_resolved = True
        row.resolved_at = datetime.now(UTC)
        row.resolved_by_id = self.actor.id
        await self.session.commit()
        return {
            "id": row.id,
            "is_resolved": True,
            "resolved_at": row.resolved_at,
            "resolved_by_id": self.actor.id,
        }

    async def forward_notification(
        self,
        notification_id: uuid.UUID,
        target_user_id: uuid.UUID | None = None,
        target_user_ids: list[uuid.UUID] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        orig = await self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.organization_id == self.actor.organization_id,
                Notification.recipient_id == self.actor.id,
            )
        )
        if not orig:
            raise NotFoundError("Notification not found")

        ids_to_process: list[uuid.UUID] = []
        if target_user_ids:
            ids_to_process.extend(target_user_ids)
        if target_user_id and target_user_id not in ids_to_process:
            ids_to_process.append(target_user_id)

        if not ids_to_process:
            raise ValidationError("At least one target employee must be selected")

        forwarded_records: list[uuid.UUID] = []
        sender_label = self.actor.email or "Colleague"
        notes_part = f" Notes: '{notes}'" if notes else ""
        forward_msg = f"[Forwarded by {sender_label}] {orig.message}{notes_part}"

        for tid in ids_to_process:
            # Find user by direct User.id, or Employee.user_id, or matching work_email
            stmt = select(User).where(
                or_(
                    User.id == tid,
                    User.email == select(Employee.work_email).where(Employee.id == tid).scalar_subquery(),
                    User.id == select(Employee.user_id).where(Employee.id == tid).scalar_subquery(),
                ),
                User.organization_id == self.actor.organization_id,
                User.is_active.is_(True),
            )
            target = await self.session.scalar(stmt)
            if not target:
                continue

            new_notif = Notification(
                id=uuid.uuid4(),
                organization_id=self.actor.organization_id,
                recipient_id=target.id,
                message=forward_msg,
                action_url=orig.action_url,
                domain=orig.domain,
                priority_tag=orig.priority_tag,
                delivery_method=orig.delivery_method,
                schedule_id=orig.schedule_id,
                forwarded_from_id=self.actor.id,
                forwarded_to_id=target.id,
                forwarded_at=datetime.now(UTC),
                forward_notes=notes,
            )
            self.session.add(new_notif)

            if orig.delivery_method in ("EMAIL", "BOTH"):
                self.session.add(
                    EmailDelivery(
                        organization_id=self.actor.organization_id,
                        recipient_id=target.id,
                        kind="FORWARDED_ALERT",
                        message=forward_msg,
                        action_url=orig.action_url,
                        next_attempt_at=datetime.now(UTC),
                    )
                )
            forwarded_records.append(new_notif.id)

        if not forwarded_records:
            raise ValidationError("No active target user accounts were found for the selected employees")

        orig.forwarded_at = datetime.now(UTC)
        await self.session.commit()
        return {
            "count": len(forwarded_records),
            "forwarded_notification_ids": forwarded_records,
        }

    # ── Notification Schedules CRUD ──────────────────────────────────────────

    def require_schedule_domain(self, domain: str) -> None:
        from app.services.notification_schedules import allowed_domains
        if domain not in allowed_domains(self.actor):
            raise ForbiddenError("You do not have permission to manage schedules in this domain")

    async def list_schedules(self, domain: str | None = None) -> list[NotificationSchedule]:
        from app.services.notification_schedules import allowed_domains
        stmt = (
            select(NotificationSchedule)
            .where(NotificationSchedule.organization_id == self.actor.organization_id,
                   NotificationSchedule.domain.in_(allowed_domains(self.actor)))
            .order_by(NotificationSchedule.created_at.desc())
        )
        if domain:
            stmt = stmt.where(NotificationSchedule.domain == domain.upper())
        return list((await self.session.scalars(stmt)).all())

    async def create_schedule(self, data: dict[str, Any]) -> NotificationSchedule:
        schedule = NotificationSchedule(
            id=uuid.uuid4(),
            organization_id=self.actor.organization_id,
            created_by_id=self.actor.id,
            title=data.get("title") or "Automated Notification Schedule",
            domain=data.get("domain", "INVENTORY").upper(),
            rule_type=data.get("rule_type", "INVENTORY_CONSUMABLES_EXPIRY"),
            criteria=data.get("criteria") or {},
            lead_time_days=int(data.get("lead_time_days", 14)),
            frequency=data.get("frequency", "DAILY").upper(),
            priority_tag=data.get("priority_tag", "IMPORTANT").upper(),
            delivery_method=data.get("delivery_method", "BOTH").upper(),
            recipient_user_ids=[str(u) for u in data.get("recipient_user_ids", [])],
            recipient_roles=data.get("recipient_roles", []),
            is_active=bool(data.get("is_active", True)),
        )
        from app.services.notification_schedules import recipients, validate_schedule

        self.require_schedule_domain(schedule.domain)
        validate_schedule(schedule)
        if schedule.is_active and not await recipients(self.session, schedule):
            raise ValidationError("Select recipients with active user accounts in this organization")
        self.session.add(schedule)
        await self.session.commit()

        # Immediately trigger initial evaluation
        await self.evaluate_schedule(schedule)
        return schedule

    async def update_schedule(
        self, schedule_id: uuid.UUID, data: dict[str, Any]
    ) -> NotificationSchedule:
        row = await self.session.scalar(
            select(NotificationSchedule).where(
                NotificationSchedule.id == schedule_id,
                NotificationSchedule.organization_id == self.actor.organization_id,
            )
        )
        if not row:
            raise NotFoundError("Schedule not found")
        self.require_schedule_domain(row.domain)

        for key, val in data.items():
            if val is not None and hasattr(row, key):
                if key == "recipient_user_ids":
                    setattr(row, key, [str(u) for u in val])
                elif key == "criteria":
                    setattr(row, key, dict(val or {}))
                elif key in ("domain", "frequency", "priority_tag", "delivery_method"):
                    setattr(row, key, str(val).upper())
                else:
                    setattr(row, key, val)

        from app.services.notification_schedules import recipients, validate_schedule

        self.require_schedule_domain(row.domain)
        validate_schedule(row)
        if row.is_active and not await recipients(self.session, row):
            raise ValidationError("Select recipients with active user accounts in this organization")
        row.last_run_at = None
        row.next_run_at = None
        await self.session.commit()
        if row.is_active:
            await self.evaluate_schedule(row)
        return row

    async def delete_schedule(self, schedule_id: uuid.UUID) -> None:
        row = await self.session.scalar(
            select(NotificationSchedule).where(
                NotificationSchedule.id == schedule_id,
                NotificationSchedule.organization_id == self.actor.organization_id,
            )
        )
        if not row:
            raise NotFoundError("Schedule not found")
        self.require_schedule_domain(row.domain)
        await self.session.delete(row)
        await self.session.commit()

    # ── Evaluation Engine ────────────────────────────────────────────────────

    async def evaluate_schedule(self, schedule: NotificationSchedule) -> int:
        from app.services.notification_schedules import evaluate

        schedule = await self.session.scalar(
            select(NotificationSchedule).where(
                NotificationSchedule.id == schedule.id,
                NotificationSchedule.organization_id == self.actor.organization_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if not schedule:
            raise NotFoundError("Schedule not found")
        self.require_schedule_domain(schedule.domain)
        return await evaluate(self.session, schedule)


async def notify_assigned_employee(
    session: AsyncSession,
    organization_id: uuid.UUID,
    employee_id: uuid.UUID | None,
    message: str,
    domain: str = "EQUIPMENT",
    priority_tag: str = "IMPORTANT",
    delivery_method: str = "BOTH",
    actor_id: uuid.UUID | None = None,
) -> bool:
    """Queue matching inbox and email alerts for the assigned employee."""
    from app.services.field_notifications import emit_event, employee_recipients

    recipients = await employee_recipients(session, organization_id, employee_id)
    if not recipients:
        return False
    await emit_event(
        session, organization_id, recipients, f"assigned:{employee_id}:{message}",
        message, domain.upper(), "EMPLOYEE_ALERT", priority_tag.upper(), delivery_method.upper(),
    )
    return True
