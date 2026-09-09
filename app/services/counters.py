import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_counter import BusinessCounter

# Maps counter entity_type -> (prefix, width). Shared "assignment" counter keeps
# ASN- numbers unique across employee and asset assignments.
PREFIXES: dict[str, tuple[str, int]] = {
    "employee": ("EMP", 6),
    "client": ("CLI", 6),
    "project": ("PRJ", 6),
    "location": ("SITE", 6),
    "assignment": ("ASN", 6),
    "asset": ("AST", 6),
    "inventory_item": ("ITM", 6),
    "inventory_store": ("STR", 6),
    "inventory_receipt": ("GRN", 6),
    "inventory_issue": ("ISS", 6),
    "inventory_return": ("RTN", 6),
    "inventory_transfer": ("TRF", 6),
    "inventory_request": ("REQ", 6),
    "inventory_adjustment": ("ADJ", 6),
    "inventory_stock_count": ("CNT", 6),
    "inventory_transaction": ("INV", 6),
    "inventory_reservation": ("RSV", 6),

}


async def next_business_number(
    session: AsyncSession, organization_id: uuid.UUID, entity_type: str
) -> str:
    """Atomically increment the org-scoped counter; must run inside a transaction."""
    prefix, width = PREFIXES[entity_type]
    query = (
        select(BusinessCounter)
        .where(
            BusinessCounter.organization_id == organization_id,
            BusinessCounter.entity_type == entity_type,
        )
        .with_for_update()
    )
    counter = (await session.scalars(query)).one_or_none()
    if counter is None:
        counter = BusinessCounter(
            organization_id=organization_id, entity_type=entity_type, current_value=0
        )
        session.add(counter)
        await session.flush()
    counter.current_value += 1
    await session.flush()
    return f"{prefix}-{counter.current_value:0{width}d}"
