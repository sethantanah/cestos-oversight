"""Idempotent bootstrap; existing role grants and passwords are never reset."""

import asyncio
import uuid

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.core.security import hash_password
from app.models import Organization, Permission, Role, User

ORGANIZATION_ID = uuid.UUID("b54b9c8e-f503-4a46-a987-5953c045ff00")
PERMISSIONS = (
    "users.read users.create users.update users.delete "
    "employees.read_basic employees.read_full employees.create employees.update "
    "employees.archive employees.assign employees.transfer "
    "employees.family.read employees.family.manage "
    "employees.emergency_contacts.read employees.emergency_contacts.manage "
    "employees.resume.read employees.resume.manage "
    "employees.documents.read employees.documents.manage employees.documents.verify "
    "employees.qualifications.read employees.qualifications.manage "
    "employees.skills.read employees.skills.manage "
    "employees.training.read employees.training.manage "
    "employees.licenses.read employees.licenses.manage "
    "employees.rotations.read employees.rotations.manage "
    "employees.asset_authorizations.read employees.asset_authorizations.manage "
    "employees.time_log.read employees.time_log.create employees.leave.read employees.leave.create "
    "employees.leave.approve employees.leave.reject "
    "employees.audit.read employees.salary.read employees.salary.manage employees.alerts.manage "
    "asset_documents.read asset_documents.manage "
    "assets.read assets.create assets.update assets.archive assets.assign assets.transfer "
    "assets.status.change assets.record_meter "
    "assets.components.read assets.components.manage "
    "assets.insurance.read assets.insurance.manage "
    "assets.registration.read assets.registration.manage "
    "assets.inspections.read assets.inspections.manage "
    "assets.defects.read assets.defects.manage "
    "assets.media.read assets.media.manage "
    "assets.audit.read assets.financial.read assets.status.override "
    "assets.meter.read assets.meter.record assets.meter.override "
    "assets.documents.read assets.documents.manage assets.documents.verify "
    "assets.location.read assets.location.manage assets.ownership.read assets.ownership.manage "
    "clients.read clients.create clients.update "
    "projects.read projects.create projects.update projects.assign_people projects.assign_assets "
    "locations.read locations.manage "
    "maintenance.read maintenance.manage inventory.read inventory.manage "
    "fuel.read fuel.manage procurement.read procurement.manage finance.read finance.manage "
    "analytics.read admin.manage"
).split()
ROLES = [
    "CEO",
    "Administrator",
    "Operations Manager",
    "Project Manager",
    "Maintenance Manager",
    "Store Manager",
    "Storekeeper",
    "Procurement",
    "HR",
    "Finance",
    "Supervisor",
    "Mechanic",
    "Operator",
    "Auditor",
]


async def seed(session: AsyncSession, settings: Settings) -> None:
    if not settings.initial_admin_email or not settings.initial_admin_password:
        raise ValueError("Set INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD before seeding")
    email = str(TypeAdapter(EmailStr).validate_python(settings.initial_admin_email)).lower()
    password = settings.initial_admin_password.get_secret_value()
    if not 12 <= len(password) <= 128:
        raise ValueError("INITIAL_ADMIN_PASSWORD must contain 12 to 128 characters")
    async with session.begin():
        # Serialize concurrent bootstrap runs on the same database.
        await session.execute(text("SELECT pg_advisory_xact_lock(736284901)"))
        organization = await session.get(Organization, ORGANIZATION_ID)
        if organization is None:
            session.add(
                Organization(
                    id=ORGANIZATION_ID,
                    name="Cestos Investments Liberia Incorporated",
                    legal_name="Cestos Investments Liberia Incorporated",
                    country="LR",
                    default_currency="USD",
                    timezone="Africa/Monrovia",
                )
            )
            await session.flush()
        permissions = {p.code: p for p in (await session.scalars(select(Permission))).all()}
        for code in PERMISSIONS:
            if code not in permissions:
                permissions[code] = Permission(code=code, description=code.replace(".", ": "))
                session.add(permissions[code])
        roles = {
            r.name: r
            for r in (
                await session.scalars(select(Role).where(Role.organization_id == ORGANIZATION_ID))
            ).all()
        }
        for name in ROLES:
            if name not in roles:
                # Only initial broad oversight roles receive grants. Domain roles start empty.
                # Existing role grants are never modified (idempotent bootstrap).
                def _is_read(code: str) -> bool:
                    return (
                        code.endswith(".read")
                        or code.endswith("read_basic")
                        or code.endswith("read_full")
                    )

                if name in {"Administrator"}:
                    grants = list(permissions.values())
                elif name in {"CEO", "Auditor"}:
                    grants = [p for p in permissions.values() if _is_read(p.code)]
                elif name == "Operations Manager":
                    grants = [
                        p
                        for code, p in permissions.items()
                        if code.startswith("employees.read")
                        or code
                        in {
                            "employees.assign",
                            "employees.transfer",
                            "employees.rotations.read",
                            "employees.asset_authorizations.read",
                            "employees.asset_authorizations.manage",
                        }
                        or code.startswith("projects.")
                        or code.startswith("assets.")
                        or code.startswith("asset_documents.")
                        or code.startswith("locations.")
                        or code.startswith("clients.")
                    ]
                elif name == "Project Manager":
                    grants = [
                        p
                        for code, p in permissions.items()
                        if code
                        in {
                            "employees.read_basic",
                            "projects.read",
                            "projects.update",
                            "projects.assign_people",
                            "projects.assign_assets",
                            "assets.read",
                            "locations.read",
                            "clients.read",
                        }
                    ]
                elif name == "Maintenance Manager":
                    grants = [
                        p
                        for code, p in permissions.items()
                        if code
                        in {
                            "assets.read",
                            "assets.update",
                            "assets.meter.read",
                            "assets.meter.record",
                            "assets.assign",
                            "assets.inspections.read",
                            "assets.inspections.manage",
                            "assets.defects.read",
                            "assets.defects.manage",
                            "asset_documents.read",
                            "locations.read",
                        }
                    ]
                elif name == "HR":
                    grants = [p for code, p in permissions.items() if code.startswith("employees.")]
                else:
                    grants = []
                roles[name] = Role(
                    organization_id=ORGANIZATION_ID,
                    name=name,
                    is_system_role=False,
                    permissions=grants,
                )
                session.add(roles[name])
        user = await session.scalar(
            select(User).where(User.organization_id == ORGANIZATION_ID, User.email == email)
        )
        if user is None:
            session.add(
                User(
                    organization_id=ORGANIZATION_ID,
                    email=email,
                    password_hash=hash_password(password),
                    first_name="Initial",
                    last_name="Administrator",
                    is_superuser=False,
                    roles=[roles["Administrator"]],
                )
            )


async def main() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await seed(session, settings)
            from scripts.sync_inventory_permissions import sync
            async with session.begin():
                await sync(session)
        print(f"Seed complete. Organization ID: {ORGANIZATION_ID}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=loop_factory)
