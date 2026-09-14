from sqlalchemy import and_, or_, select
from sqlalchemy.exc import InvalidRequestError

from app.core.dependencies import scoped_roles
from app.core.exceptions import NotFoundError
from app.models import Employee
from app.models.document_library import LibraryDocument as D


def permissions(actor):
    if not actor:
        return set()
    try:
        return {p.code for role in scoped_roles(actor) for p in role.permissions}
    except (InvalidRequestError, AttributeError):
        return set()


def is_document_admin(actor):
    return actor.is_superuser or "documents.admin" in permissions(actor)


def personal_scope(actor):
    return or_(
        D.owner_id == actor.id,
        D.employee_id.in_(
            select(Employee.id).where(
                Employee.organization_id == actor.organization_id, Employee.user_id == actor.id
            )
        ),
    )


def visible_scope(actor):
    codes = permissions(actor)
    if actor.is_superuser or codes.intersection({"documents.admin", "documents.read_all"}):
        return and_(
            D.organization_id == actor.organization_id,
            D.is_active.is_(True),
            or_(
                and_(D.visibility == "SUPER_PRIVATE", D.private_to_id == actor.id),
                D.visibility != "SUPER_PRIVATE",
            ),
        )
    oversight = []
    for category, grants in {
        "People": {
            "employees.documents.read",
            "employee_documents.read",
            "employees.read_sensitive",
        },
        "Equipment": {"assets.documents.read", "asset_documents.read"},
        "Inventory": {"inventory.admin", "inventory.catalog.manage"},
        "Projects": {"projects.update"},
        "Leave": {"employees.leave.approve"},
    }.items():
        if codes.intersection(grants):
            oversight.append(D.category == category)
    return and_(
        D.organization_id == actor.organization_id,
        D.is_active.is_(True),
        or_(
            and_(D.visibility == "SUPER_PRIVATE", D.private_to_id == actor.id),
            and_(
                D.visibility != "SUPER_PRIVATE",
                or_(D.visibility == "PUBLIC", personal_scope(actor), *oversight),
            ),
        ),
    )


async def require_document_path(session, actor, path):
    document = await session.scalar(select(D).where(D.storage_path == path, visible_scope(actor)))
    if document is None:
        raise NotFoundError("Document not found")
    return document
