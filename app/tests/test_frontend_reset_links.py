"""Reset emails must use the deployed frontend and never the removed test UI."""
from types import SimpleNamespace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.hr import EmailDelivery, PasswordSetup
from app.services import mail
from app.tests.test_field_notifications import field_db as field_fixture

field_db = field_fixture
FRONTEND = "https://cestos.qoteport.workers.dev"


def settings(url):
    return Settings(_env_file=None, database_url="postgresql+psycopg://test:test@localhost/test",
        jwt_secret_key="x" * 40, public_base_url=url)


@pytest.mark.parametrize("suffix", ["", "/", "/sign-up-login", "/sign-up-login/"])
def test_frontend_origin_is_normalized(suffix):
    assert settings(FRONTEND + suffix).public_base_url == FRONTEND


@pytest.mark.parametrize("url", [
    "https://cestos-oversight.fly.dev", "https://cestos-oversight.fly.dev/test-ui/",
    FRONTEND + "/test-ui", FRONTEND + "/test_ui", FRONTEND + "/api/v1",
    FRONTEND + "/#reset=", FRONTEND + "?reset=", "javascript:alert(1)",
])
def test_legacy_or_non_frontend_urls_are_rejected(url):
    with pytest.raises(ValidationError, match="frontend origin"):
        settings(url)


async def test_setup_email_links_to_frontend(field_db, monkeypatch):
    f = field_db
    PasswordSetup.__table__.create(f.session.get_bind())
    f.worker.setup_required = True
    f.session.add(EmailDelivery(organization_id=f.org.id, recipient_id=f.worker.id,
        kind="SETUP", message="Set your password", next_attempt_at=datetime.now(UTC)))
    f.session.commit()
    sent = []
    monkeypatch.setattr(mail, "send_email", lambda *args: sent.append(args))
    assert await mail.deliver_one(f.db, SimpleNamespace(smtp_host="test", smtp_from="test@example.com", public_base_url=FRONTEND))
    assert len(sent) == 1
    body = sent[0][3]
    assert FRONTEND + "/sign-up-login#reset=" in body
    assert "test-ui" not in body and "cestos-oversight.fly.dev" not in body
