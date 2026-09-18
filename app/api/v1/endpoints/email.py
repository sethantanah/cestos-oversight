"""SMTP Email Delivery API Endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.dependencies import request_settings
from app.services.mail import send_email

router = APIRouter(prefix="/email", tags=["email"])


class SendEmailRequest(BaseModel):
    recipient_email: EmailStr = Field(..., description="Recipient email address")
    subject: str = Field(..., min_length=1, description="Email subject line")
    html_template: str = Field(..., min_length=1, description="HTML email template")
    text_content: str | None = Field(None, description="Optional plain-text fallback content")
    sender_email: EmailStr | None = Field(None, description="Optional custom sender email address")
    sender_password: str | None = Field(None, description="Optional custom sender SMTP password")
    sender_name: str | None = Field(None, description="Optional custom sender display name (e.g. 'Cestos Operations')")

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for alt_to in ("to", "recipient", "to_email", "dest_email"):
                if alt_to in data and "recipient_email" not in data:
                    data["recipient_email"] = data[alt_to]
            for alt_html in ("html_content", "html", "template", "body_html"):
                if alt_html in data and "html_template" not in data:
                    data["html_template"] = data[alt_html]
            for alt_text in ("body", "text", "body_text"):
                if alt_text in data and "text_content" not in data:
                    data["text_content"] = data[alt_text]
            for alt_from in ("from_email", "sender", "from", "smtp_username", "username"):
                if alt_from in data and "sender_email" not in data:
                    data["sender_email"] = data[alt_from]
            for alt_pass in ("from_password", "smtp_password", "password", "auth_password"):
                if alt_pass in data and "sender_password" not in data:
                    data["sender_password"] = data[alt_pass]
            for alt_name in ("from_name", "sender_name", "display_name", "name", "from_display_name"):
                if alt_name in data and "sender_name" not in data:
                    data["sender_name"] = data[alt_name]
        return data

    model_config = {
        "json_schema_extra": {
            "example": {
                "recipient_email": "user@example.com",
                "subject": "Notification",
                "html_template": "<h1>Hello</h1><p>This is a test email.</p>",
                "text_content": "Hello. This is a test email.",
                "sender_email": "custom_sender@stableserver.net",
                "sender_password": "custom_smtp_password",
                "sender_name": "Cestos Operations"
            }
        }
    }


class SendEmailResponse(BaseModel):
    status: str
    message: str
    recipient: str
    subject: str
    sender_email: str
    sender_name: str | None = None


@router.post("/send", response_model=SendEmailResponse, status_code=status.HTTP_200_OK)
@router.post("", response_model=SendEmailResponse, status_code=status.HTTP_200_OK)
async def dispatch_email(
    payload: SendEmailRequest,
    settings: Settings = Depends(request_settings),
) -> dict[str, Any]:
    """Send an HTML email template to the specified recipient using backend SMTP configuration."""
    if not settings.smtp_host:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SMTP host is not configured on the server.",
        )

    sender_email = payload.sender_email or settings.smtp_from
    if not sender_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sender email address is required (provide sender_email or configure SMTP_FROM).",
        )
    sender_name = payload.sender_name or settings.smtp_from_name

    try:
        await run_in_threadpool(
            send_email,
            settings,
            str(payload.recipient_email),
            payload.subject,
            payload.text_content or "",
            payload.html_template,
            str(payload.sender_email) if payload.sender_email else None,
            payload.sender_password,
            payload.sender_name,
        )
        return {
            "status": "success",
            "message": f"Email successfully dispatched to {payload.recipient_email}",
            "recipient": str(payload.recipient_email),
            "subject": payload.subject,
            "sender_email": str(sender_email),
            "sender_name": sender_name,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deliver email via SMTP: {str(exc)}",
        )
