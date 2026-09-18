"""Tests for SMTP email delivery endpoint."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_send_email_endpoint(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://postgres:Admin32@localhost:5432/cestos",
        jwt_secret_key="a-test-only-secret-that-is-over-32-characters",
        smtp_host="s20849.use2.stableserver.net",
        smtp_port=465,
        smtp_from="test@example.com",
        smtp_username="test@example.com",
        smtp_use_ssl=True,
    )
    app = create_app(settings)
    client = TestClient(app)

    sent_messages = []

    def mock_send_email(settings_arg, to, subject, body, html_body=None, sender_email=None, sender_password=None, sender_name=None):
        sent_messages.append({
            "to": to,
            "subject": subject,
            "body": body,
            "html_body": html_body,
            "sender_name": sender_name,
        })

    monkeypatch.setattr("app.api.v1.endpoints.email.send_email", mock_send_email)

    response = client.post(
        "/api/v1/email/send",
        json={
            "recipient_email": "recipient@example.com",
            "subject": "Test HTML Email",
            "html_template": "<h1>Welcome</h1><p>Test HTML Template</p>",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["recipient"] == "recipient@example.com"
    assert data["sender_email"] == "test@example.com"
    assert data["sender_name"] == "Cestos Operations"
    assert len(sent_messages) == 1
    assert sent_messages[0]["to"] == "recipient@example.com"
    assert sent_messages[0]["html_body"] == "<h1>Welcome</h1><p>Test HTML Template</p>"


def test_send_email_endpoint_aliases(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://postgres:Admin32@localhost:5432/cestos",
        jwt_secret_key="a-test-only-secret-that-is-over-32-characters",
        smtp_host="s20849.use2.stableserver.net",
        smtp_port=465,
        smtp_from="test@example.com",
        smtp_username="test@example.com",
        smtp_use_ssl=True,
    )
    app = create_app(settings)
    client = TestClient(app)

    sent_messages = []

    def mock_send_email(settings_arg, to, subject, body, html_body=None, sender_email=None, sender_password=None, sender_name=None):
        sent_messages.append({
            "to": to,
            "subject": subject,
            "body": body,
            "html_body": html_body,
            "sender_name": sender_name,
        })

    monkeypatch.setattr("app.api.v1.endpoints.email.send_email", mock_send_email)

    response = client.post(
        "/api/v1/email",
        json={
            "to": "user@example.com",
            "subject": "Alias Test",
            "html_content": "<p>Aliased template</p>",
            "text_content": "Plain text fallback",
            "from_name": "Custom Alias Name",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["sender_name"] == "Custom Alias Name"
    assert len(sent_messages) == 1
    assert sent_messages[0]["to"] == "user@example.com"
    assert sent_messages[0]["html_body"] == "<p>Aliased template</p>"
    assert sent_messages[0]["body"] == "Plain text fallback"
    assert sent_messages[0]["sender_name"] == "Custom Alias Name"


def test_send_email_endpoint_custom_sender(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://postgres:Admin32@localhost:5432/cestos",
        jwt_secret_key="a-test-only-secret-that-is-over-32-characters",
        smtp_host="s20849.use2.stableserver.net",
        smtp_port=465,
        smtp_use_ssl=True,
    )
    app = create_app(settings)
    client = TestClient(app)

    sent_messages = []

    def mock_send_email(settings_arg, to, subject, body, html_body=None, sender_email=None, sender_password=None, sender_name=None):
        sent_messages.append({
            "to": to,
            "subject": subject,
            "body": body,
            "html_body": html_body,
            "sender_email": sender_email,
            "sender_password": sender_password,
            "sender_name": sender_name,
        })

    monkeypatch.setattr("app.api.v1.endpoints.email.send_email", mock_send_email)

    response = client.post(
        "/api/v1/email/send",
        json={
            "to": "recipient@example.com",
            "from": "custom.sender@stableserver.net",
            "password": "secretpassword123",
            "name": "Custom Sender Name",
            "subject": "Custom Sender Email Test",
            "html": "<h1>Custom Sender</h1>",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["sender_email"] == "custom.sender@stableserver.net"
    assert data["sender_name"] == "Custom Sender Name"
    assert len(sent_messages) == 1
    assert sent_messages[0]["sender_email"] == "custom.sender@stableserver.net"
    assert sent_messages[0]["sender_password"] == "secretpassword123"
    assert sent_messages[0]["sender_name"] == "Custom Sender Name"
