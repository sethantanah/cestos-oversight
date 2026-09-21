"""Durable SMTP queue. No password or reset token is stored in the mail queue."""

import asyncio
import secrets
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

import structlog
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.security import token_hash
from app.models import Organization, User
from app.models.hr import EmailDelivery, PasswordSetup
from app.services.hr import generate_alerts


def send_email(
    settings: Settings,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    sender_email: str | None = None,
    sender_password: str | None = None,
    sender_name: str | None = None,
) -> None:
    smtp_host = settings.smtp_host
    if not smtp_host:
        raise ValueError("SMTP_HOST is required in server settings")

    from_address = sender_email or settings.smtp_from
    if not from_address:
        raise ValueError("Sender email address is required")

    from_name = sender_name or settings.smtp_from_name
    login_username = sender_email or settings.smtp_username
    login_password = sender_password if sender_password is not None else (
        settings.smtp_password.get_secret_value() if settings.smtp_password else ""
    )

    message = EmailMessage()
    if from_name:
        message["From"] = formataddr((from_name, from_address))
    else:
        message["From"] = from_address
    message["To"] = to
    message["Subject"] = subject
    if html_body:
        message.set_content(body or "Please view this email in an HTML-compatible email client.")
        message.add_alternative(html_body, subtype="html")
    else:
        message.set_content(body)
    connection = (
        smtplib.SMTP_SSL(
            smtp_host, settings.smtp_port, timeout=15, context=ssl.create_default_context()
        )
        if settings.smtp_use_ssl
        else smtplib.SMTP(smtp_host, settings.smtp_port, timeout=15)
    )
    with connection as smtp:
        if settings.smtp_starttls and not settings.smtp_use_ssl:
            smtp.starttls(context=ssl.create_default_context())
        if login_username:
            smtp.login(login_username, login_password)
        smtp.send_message(message)


async def deliver_one(session: AsyncSession, settings: Settings) -> bool:
    if not settings.smtp_host or not settings.smtp_from:
        return False
    now = datetime.now(UTC)
    job = await session.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.status == "PENDING", EmailDelivery.next_attempt_at <= now)
        .order_by(EmailDelivery.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not job:
        return False
    user = await session.scalar(
        select(User)
        .where(User.id == job.recipient_id, User.organization_id == job.organization_id)
        .with_for_update()
    )
    organization = await session.get(Organization, job.organization_id)
    if (
        not user
        or not user.is_active
        or user.archived_at
        or not organization
        or not organization.is_active
    ):
        job.status = "CANCELLED"
        await session.commit()
        return True
    body = job.message
    subject = {
        "ALERT": "Cestos contract expiry reminder",
        "CONTRACT_EXPIRY": "Cestos contract expiry reminder",
        "PROJECT_ASSIGNMENT": "Cestos project assignment update",
        "WORK_ORDER_UPDATE": "Cestos maintenance work order update",
        "WORK_ORDER_OVERDUE": "Cestos overdue maintenance alert",
        "WORK_ORDER_DUE": "Cestos maintenance due reminder",
        "LEAVE_REQUESTED": "Cestos team leave request",
        "LEAVE_DECISION": "Cestos leave request decision",
    }.get(job.kind, "Cestos notification")
    setup = None
    if job.kind == "SETUP":
        if not user.setup_required:
            job.status = "CANCELLED"
            await session.commit()
            return True
        raw = secrets.token_urlsafe(48)
        issued_at = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        subject = f"Cestos password setup/reset - {issued_at}"
        setup = PasswordSetup(
            organization_id=job.organization_id,
            user_id=user.id,
            token_hash=token_hash(raw),
            expires_at=now + timedelta(hours=24),
        )
        base_url = settings.public_base_url.rstrip('/')
        if '#reset=' in base_url or '?reset=' in base_url:
            reset_url = f"{base_url}{raw}"
        elif base_url.endswith('/sign-up-login') or base_url.endswith('/test-ui'):
            reset_url = f"{base_url}/#reset={raw}"
        else:
            reset_url = f"{base_url}/sign-up-login#reset={raw}"

        body += (
            f"\n\nReset link issued: {issued_at}.\n"
            "This link replaces earlier setup/reset links. Use the link in this message.\n"
            "Open this single-use link within 24 hours:\n"
            f"{reset_url}\n\n"
            "If you did not expect this invitation, contact your administrator."
        )
    else:
        destination = (
            "/field-portal/notifications" if user.is_field_portal_only
            else "/workspace/hr/notifications"
        )
        body += f"\n\nView your notifications: {settings.public_base_url.rstrip('/')}{destination}"
    try:
        await run_in_threadpool(
            send_email,
            settings,
            user.email,
            subject,
            body,
        )
        if setup:
            await session.execute(
                update(PasswordSetup)
                .where(PasswordSetup.user_id == user.id, PasswordSetup.used_at.is_(None))
                .values(used_at=now)
            )
            session.add(setup)
        job.status = "SENT"
        job.last_error = None
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        job.attempts += 1
        job.last_error = f"SMTP delivery failed ({type(exc).__name__}); check configuration and recipient"
        job.next_attempt_at = now + timedelta(minutes=min(2 ** min(job.attempts, 10), 360))
        if job.attempts >= 10:
            job.status = "FAILED"
    await session.commit()
    return True


async def scheduler_tick(app: FastAPI) -> None:
    from app.services.field_notifications import generate_field_alerts
    from app.services.notification_schedules import run_due_schedules

    # Separate transactions and failure boundaries keep a broken rule from starving mail.
    for generator in (generate_alerts, generate_field_alerts):
        try:
            async with app.state.session_factory() as session:
                await generator(session)
        except Exception:
            structlog.get_logger().exception("alert_generation_failed", generator=generator.__name__)
    try:
        await run_due_schedules(app.state.session_factory)
    except Exception:
        structlog.get_logger().exception("notification_schedules_failed")
    for _ in range(20):
        try:
            async with app.state.session_factory() as session:
                if not await deliver_one(session, app.state.settings):
                    break
        except Exception:
            structlog.get_logger().exception("email_queue_failed")
            break


async def scheduler(app: FastAPI) -> None:
    while True:
        await scheduler_tick(app)
        await asyncio.sleep(app.state.settings.scheduler_interval_seconds)
