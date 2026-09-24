"""Durable SMTP queue. Delivers branded HTML emails for all notification kinds."""

import asyncio
import html
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


# ---------------------------------------------------------------------------
# HTML Template Engine
# ---------------------------------------------------------------------------

def _base_html(title: str, preheader: str, content_html: str, cta_url: str = "", cta_label: str = "") -> str:
    """Render a branded Cestos email in a clean, mobile-friendly HTML wrapper."""
    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
        <tr>
          <td align="center" style="padding:24px 0 8px;">
            <a href="{html.escape(cta_url, quote=True)}" target="_blank"
               style="display:inline-block;padding:14px 32px;background:#165DAB;color:#ffffff;
                      font-size:15px;font-weight:700;text-decoration:none;border-radius:0;
                      letter-spacing:0.3px;">
              {html.escape(cta_label)}
            </a>
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:4px 0 16px;font-size:11px;color:#71839B;">
            Or copy this link: <a href="{html.escape(cta_url, quote=True)}" style="color:#165DAB;word-break:break-all;">{html.escape(cta_url)}</a>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{html.escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:#EEF4FB;font-family:'Segoe UI',Arial,sans-serif;">
  <span style="display:none;max-height:0;overflow:hidden;">{html.escape(preheader)}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;</span>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#EEF4FB;padding:32px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border:1px solid #D6E2F0;border-top:5px solid #D62828;
                      overflow:hidden;box-shadow:0 2px 12px rgba(19,59,110,0.10);max-width:600px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="background:#173F73;padding:28px 36px;text-align:left;">
              <span style="font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">
                Cestos
              </span>
              <span style="font-size:12px;color:#DCEBFC;display:block;margin-top:2px;letter-spacing:1px;text-transform:uppercase;">
                Operations Platform
              </span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px 36px 8px;">
              {content_html}
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td style="padding:0 36px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                {cta_block}
              </table>
            </td>
          </tr>

          <!-- Divider -->
          <tr>
            <td style="padding:0 36px;">
              <hr style="border:none;border-top:1px solid #D6E2F0;margin:8px 0 24px;" />
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:0 36px 32px;font-size:11px;color:#71839B;line-height:1.6;">
              This is an automated message from the Cestos Operations Platform.
              Do not reply to this email. If you have questions, contact your system administrator.<br /><br />
              &copy; {datetime.now(UTC).year} Cestos &mdash; All rights reserved.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _info_row(label: str, value: str) -> str:
    return f"""<tr>
      <td style="padding:5px 12px 5px 0;font-size:13px;color:#53657D;white-space:nowrap;vertical-align:top;">{html.escape(str(label))}</td>
      <td style="padding:5px 0;font-size:13px;color:#173F73;font-weight:600;vertical-align:top;">{html.escape(str(value))}</td>
    </tr>"""


def _badge(text: str, color: str = "#165DAB") -> str:
    safe_color = color if color.lower() in {"#165dab", "#d62828"} else "#165DAB"
    return f'<span style="display:inline-block;padding:3px 10px;background:#EEF4FB;color:{safe_color};border:1px solid {safe_color};border-radius:0;font-size:11px;font-weight:700;letter-spacing:0.5px;">{html.escape(text)}</span>'


def notification_portal_path(user: User) -> str:
    """Return a notification destination that is reachable in the user's portal."""
    portal_type = str(getattr(user, "portal_type", "FULL") or "FULL").upper()
    if getattr(user, "is_field_portal_only", False) or portal_type == "FIELD":
        return "/field-portal/notifications"
    portal_paths = {
        "FIELD_ADMIN": "/field-admin-portal?tab=NOTIFICATIONS",
        "HR": "/hr-portal?tab=NOTIFICATIONS",
        "FINANCE": "/finance-portal?tab=NOTIFICATIONS",
        "EXECUTIVE": "/executive-portal?tab=NOTIFICATIONS",
    }
    return portal_paths.get(portal_type, "/workspace/hr/notifications")


def build_html_email(
    kind: str,
    body_text: str,
    user_name: str,
    reset_url: str = "",
    issued_at: str = "",
    portal_url: str = "",
) -> tuple[str, str]:
    """
    Returns (subject, html_body) for the given email kind.
    body_text is the plain-text message from the queue record (used for detail copy).
    """
    first_name = html.escape(user_name.split()[0] if user_name else "there")
    safe_body_text = html.escape(body_text)

    if kind == "SETUP":
        subject = f"Set up your Cestos account password"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#173F73;font-weight:800;">Welcome to Cestos 👋</h2>
        <p style="margin:0 0 20px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>,<br /><br />
          Your account has been created on the Cestos Operations Platform.
          Use the button below to set your password and access your workspace.
        </p>
        <div style="background:#F6F9FD;border:1px solid #D6E2F0;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <table cellpadding="0" cellspacing="0">
            {_info_row("Issued:", issued_at)}
            {_info_row("Expires:", "24 hours from issue")}
            {_info_row("Use:", "Single-use link — expires after first click")}
          </table>
        </div>
        <p style="margin:0;font-size:13px;color:#71839B;">
          If you did not expect this email, please contact your administrator immediately.
        </p>"""
        return subject, _base_html(subject, "Set your Cestos password to get started.", content, reset_url, "Set My Password →")

    if kind in ("RESET", "SETUP_RESET"):
        subject = f"Reset your Cestos password"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#173F73;font-weight:800;">Password Reset Requested</h2>
        <p style="margin:0 0 20px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>,<br /><br />
          A password reset was initiated for your Cestos account by your administrator.
          Use the button below to choose a new password.
        </p>
        <div style="background:#FEF2F2;border:1px solid #F2B8BE;border-radius:0;padding:14px 18px;margin-bottom:20px;">
          <strong style="font-size:13px;color:#B4232F;">⚠ Security Notice</strong>
          <p style="margin:6px 0 0;font-size:13px;color:#B4232F;line-height:1.5;">
            All your active sessions have been revoked. This link expires in <strong>24 hours</strong> and is single-use only.
          </p>
        </div>
        <div style="background:#F6F9FD;border:1px solid #D6E2F0;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <table cellpadding="0" cellspacing="0">
            {_info_row("Reset issued:", issued_at)}
            {_info_row("Valid for:", "24 hours")}
          </table>
        </div>
        <p style="margin:0;font-size:13px;color:#71839B;">
          If you did not request this reset, contact your administrator immediately.
        </p>"""
        return subject, _base_html(subject, "Reset your Cestos account password.", content, reset_url, "Reset My Password →")

    if kind in ("ALERT", "CONTRACT_EXPIRY"):
        subject = "Contract expiry reminder — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#D62828;font-weight:800;">⚠ Contract Expiry Alert</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>, you have a contract that is nearing its expiry date.
        </p>
        <div style="background:#FEF2F2;border:1px solid #F2B8BE;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#B4232F;line-height:1.6;">{safe_body_text}</p>
        </div>
        <p style="margin:0;font-size:13px;color:#71839B;">Log in to Cestos to review and renew the contract.</p>"""
        return subject, _base_html(subject, "A contract is expiring soon.", content, portal_url, "View in Cestos →")

    if kind == "PROJECT_ASSIGNMENT":
        subject = "Project assignment update — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#173F73;font-weight:800;">📋 Project Assignment Update</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>, your project assignment has been updated.
        </p>
        <div style="background:#EEF4FB;border:1px solid #D6E2F0;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#173F73;line-height:1.6;">{safe_body_text}</p>
        </div>
        <p style="margin:0;font-size:13px;color:#71839B;">Log in to Cestos to view your full assignment details.</p>"""
        return subject, _base_html(subject, "Your project assignment has been updated.", content, portal_url, "View Assignment →")

    if kind == "WORK_ORDER_UPDATE":
        subject = "Work order update — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#173F73;font-weight:800;">🔧 Work Order Update</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>, a maintenance work order assigned to you has been updated.
        </p>
        <div style="background:#EEF4FB;border:1px solid #D6E2F0;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#173F73;line-height:1.6;">{safe_body_text}</p>
        </div>"""
        return subject, _base_html(subject, "A work order has been updated.", content, portal_url, "View Work Order →")

    if kind == "WORK_ORDER_OVERDUE":
        subject = "⚠ Overdue maintenance alert — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#D62828;font-weight:800;">⚠ Overdue Maintenance Alert</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>, a maintenance work order is <strong>overdue</strong> and requires immediate attention.
        </p>
        <div style="background:#FEF2F2;border:1px solid #F2B8BE;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#B4232F;line-height:1.6;">{safe_body_text}</p>
        </div>"""
        return subject, _base_html(subject, "An overdue work order needs your attention.", content, portal_url, "View Now →")

    if kind == "WORK_ORDER_DUE":
        subject = "Maintenance due reminder — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#D62828;font-weight:800;">🕐 Maintenance Due Soon</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>, a scheduled maintenance task is coming due.
        </p>
        <div style="background:#FEF2F2;border:1px solid #F2B8BE;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#B4232F;line-height:1.6;">{safe_body_text}</p>
        </div>"""
        return subject, _base_html(subject, "Scheduled maintenance is due soon.", content, portal_url, "View Schedule →")

    if kind == "LEAVE_REQUESTED":
        subject = "Leave request submitted — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#173F73;font-weight:800;">📅 Leave Request Submitted</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>, a leave request has been submitted and is pending approval.
        </p>
        <div style="background:#EEF4FB;border:1px solid #D6E2F0;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#173F73;line-height:1.6;">{safe_body_text}</p>
        </div>"""
        return subject, _base_html(subject, "A leave request is pending your review.", content, portal_url, "Review Request →")

    if kind == "LEAVE_DECISION":
        subject = "Leave request decision — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#173F73;font-weight:800;">📅 Leave Request Decision</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">
          Hi <strong>{first_name}</strong>, a decision has been made on your leave request.
        </p>
        <div style="background:#EEF4FB;border:1px solid #D6E2F0;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#173F73;line-height:1.6;">{safe_body_text}</p>
        </div>"""
        return subject, _base_html(subject, "Your leave request has a decision.", content, portal_url, "View Details →")

    finance_notification_labels = {
        "PURCHASE_ORDER_SUBMITTED": ("Purchase order submitted for approval", "A purchase order needs executive review."),
        "PURCHASE_ORDER_APPROVED": ("Purchase order approved", "A purchase order has been approved."),
        "EXPENSE_RAISED": ("Expense raised", "Your expense was submitted to Finance."),
        "EXPENSE_SUBMITTED_TO_FINANCE": ("Expense submitted to Finance", "A new expense is ready for Finance review."),
        "FINANCE_EXPENSE_PAYMENT": ("Finance payment recorded", "Finance has recorded a payment against your expense."),
    }
    if kind in finance_notification_labels:
        label, preheader = finance_notification_labels[kind]
        subject = f"{label} — Cestos"
        content = f"""
        <h2 style="margin:0 0 8px;font-size:22px;color:#173F73;font-weight:800;">{html.escape(label)}</h2>
        <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">Hi <strong>{first_name}</strong>,</p>
        <div style="background:#EEF4FB;border:1px solid #D6E2F0;border-left:4px solid #D62828;border-radius:0;padding:16px 20px;margin-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#173F73;line-height:1.6;">{safe_body_text}</p>
        </div>"""
        return subject, _base_html(subject, preheader, content, portal_url, "Open Record →")

    # Generic fallback
    subject = "Cestos notification"
    content = f"""
    <h2 style="margin:0 0 8px;font-size:20px;color:#173F73;font-weight:800;">Cestos Notification</h2>
    <p style="margin:0 0 16px;font-size:15px;color:#53657D;line-height:1.6;">Hi <strong>{first_name}</strong>,</p>
    <div style="background:#F6F9FD;border:1px solid #D6E2F0;border-radius:0;padding:16px 20px;margin-bottom:20px;">
      <p style="margin:0;font-size:14px;color:#173F73;line-height:1.6;">{safe_body_text}</p>
    </div>"""
    return subject, _base_html(subject, "You have a new notification from Cestos.", content, portal_url, "Open Cestos →")


# ---------------------------------------------------------------------------
# SMTP transport
# ---------------------------------------------------------------------------

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
    message["From"] = formataddr((from_name, from_address)) if from_name else from_address
    message["To"] = to
    message["Subject"] = subject
    if html_body:
        message.set_content(body or "Please view this email in an HTML-compatible email client.")
        message.add_alternative(html_body, subtype="html")
    else:
        message.set_content(body)

    connection = (
        smtplib.SMTP_SSL(smtp_host, settings.smtp_port, timeout=15, context=ssl.create_default_context())
        if settings.smtp_use_ssl
        else smtplib.SMTP(smtp_host, settings.smtp_port, timeout=15)
    )
    with connection as smtp:
        if settings.smtp_starttls and not settings.smtp_use_ssl:
            smtp.starttls(context=ssl.create_default_context())
        if login_username:
            smtp.login(login_username, login_password)
        smtp.send_message(message)


# ---------------------------------------------------------------------------
# Queue processor
# ---------------------------------------------------------------------------

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

    # Determine portal destination URL
    portal_path = job.action_url or notification_portal_path(user)
    if not portal_path.startswith("/") or portal_path.startswith("//"):
        portal_path = notification_portal_path(user)
    portal_url = f"{settings.public_base_url.rstrip('/')}{portal_path}"
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email

    setup = None
    reset_url = ""
    issued_at = ""

    if job.kind == "SETUP":
        if not user.setup_required:
            job.status = "CANCELLED"
            await session.commit()
            return True
        raw = secrets.token_urlsafe(48)
        issued_at = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        setup = PasswordSetup(
            organization_id=job.organization_id,
            user_id=user.id,
            token_hash=token_hash(raw),
            expires_at=now + timedelta(hours=24),
        )
        base = settings.public_base_url.rstrip("/")
        reset_url = f"{base}/sign-up-login#reset={raw}"

    # Build subject + HTML
    email_subject, html_body = build_html_email(
        kind=job.kind,
        body_text=job.message or "",
        user_name=user_name,
        reset_url=reset_url,
        issued_at=issued_at,
        portal_url=portal_url,
    )

    # Plain-text fallback
    plain_text = job.message or ""
    if reset_url:
        plain_text += f"\n\nReset link: {reset_url}\nExpires in 24 hours. Single-use only."
    else:
        plain_text += f"\n\nView in Cestos: {portal_url}"

    try:
        await run_in_threadpool(
            send_email,
            settings,
            user.email,
            email_subject,
            plain_text,
            html_body,
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
        job.last_error = f"SMTP delivery failed ({type(exc).__name__}): {exc}"
        job.next_attempt_at = now + timedelta(minutes=min(2 ** min(job.attempts, 10), 360))
        if job.attempts >= 10:
            job.status = "FAILED"
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

async def scheduler_tick(app: FastAPI) -> None:
    from app.services.field_notifications import generate_field_alerts
    from app.services.notification_schedules import run_due_schedules

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
