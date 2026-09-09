"""Durable SMTP queue. No password or reset token is stored in the mail queue."""

import asyncio
import secrets
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

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


def send_email(settings: Settings, to: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_from:
        raise ValueError("SMTP_HOST and SMTP_FROM are required")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    connection = (
        smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=15, context=ssl.create_default_context()
        )
        if settings.smtp_use_ssl
        else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    )
    with connection as smtp:
        if settings.smtp_starttls and not settings.smtp_use_ssl:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value() if settings.smtp_password else "",
            )
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
    subject = "Cestos contract expiry reminder"
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
        body += (
            f"\n\nReset link issued: {issued_at}.\n"
            "This link replaces earlier setup/reset links. Use the link in this message.\n"
            "Open this single-use link within 24 hours:\n"
            f"{settings.public_base_url.rstrip('/')}/#reset={raw}\n\n"
            "If you did not expect this invitation, contact your administrator."
        )
    else:
        body += f"\n\nSign in to Cestos: {settings.public_base_url.rstrip('/')}/#notifications"
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
    except (OSError, smtplib.SMTPException):
        job.attempts += 1
        job.last_error = "SMTP delivery failed; check SMTP configuration and recipient address"
        job.next_attempt_at = now + timedelta(minutes=min(2 ** min(job.attempts, 10), 360))
        if job.attempts >= 10:
            job.status = "FAILED"
    await session.commit()
    return True


async def scheduler(app: FastAPI) -> None:
    while True:
        try:
            async with app.state.session_factory() as session:
                await generate_alerts(session)
            for _ in range(20):
                async with app.state.session_factory() as session:
                    if not await deliver_one(session, app.state.settings):
                        break
        except asyncio.CancelledError:
            raise
        except Exception:
            structlog.get_logger().error("hr_scheduler_failed")
        await asyncio.sleep(app.state.settings.scheduler_interval_seconds)
