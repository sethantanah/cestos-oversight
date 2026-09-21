import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ForbiddenError
from app.models.employee import DocumentType
from app.services.workforce import DocumentService


def actor(names, foreign=False):
    org = uuid.uuid4()
    return SimpleNamespace(
        is_superuser=False,
        organization_id=org,
        roles=[
            SimpleNamespace(
                name=name, organization_id=uuid.uuid4() if foreign else org, is_system_role=False
            )
            for name in names
        ],
    )


@pytest.mark.parametrize(
    "names",
    [["Supervisor", "Maintenance Manager", "Project Manager"], ["HR Manager"], ["Admin Assistant"]],
)
@pytest.mark.asyncio
async def test_contract_upload_denied_before_storage_or_database(names):
    session = AsyncMock()
    storage = SimpleNamespace(save=AsyncMock())
    service = DocumentService(session, actor(names))
    with pytest.raises(ForbiddenError):
        await service.upload(
            uuid.uuid4(),
            b"contract",
            "contract.pdf",
            "application/pdf",
            storage,
            DocumentType.EMPLOYMENT_CONTRACT,
        )
    storage.save.assert_not_called()
    session.scalars.assert_not_called()


@pytest.mark.parametrize("role", ["HR", "Admin", "Administrator"])
def test_hr_admin_role_scope(role):
    DocumentService(None, actor([role]))._require_contract_editor(DocumentType.EMPLOYMENT_CONTRACT)
    with pytest.raises(ForbiddenError):
        DocumentService(None, actor([role], foreign=True))._require_contract_editor(
            DocumentType.EMPLOYMENT_CONTRACT
        )


def test_other_documents_not_restricted_by_contract_policy():
    DocumentService(None, actor(["Supervisor"]))._require_contract_editor(DocumentType.OTHER)


@pytest.mark.asyncio
async def test_basic_profile_reader_cannot_manage_accounts_or_archive():
    from app.core.dependencies import require_permission

    user = actor(["Supervisor", "Maintenance Manager", "Project Manager"])
    for role in user.roles:
        role.permissions = [SimpleNamespace(code="employees.read_basic")]
    for code in ["users.update", "employees.archive"]:
        with pytest.raises(ForbiddenError):
            await require_permission(code)(user=user, session=AsyncMock())
