import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import (
    ActorMixin,
    ArchiveMixin,
    OrganizationMixin,
    TimestampMixin,
    UUIDMixin,
)


class PoStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SENT_TO_SUPPLIER = "SENT_TO_SUPPLIER"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PurchaseOrder(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_purchase_orders_org_supplier", "organization_id", "supplier_id"),
        Index("ix_purchase_orders_org_status", "organization_id", "status"),
        Index("ix_purchase_orders_number", "organization_id", "po_number", unique=True),
    )

    po_number: Mapped[str] = mapped_column(String(50))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fuel_suppliers.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_requests.id"), index=True)
    status: Mapped[PoStatus] = mapped_column(Enum(PoStatus, name="po_status"), default=PoStatus.DRAFT)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.0"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        "PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseOrderItem(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        Index("ix_po_items_org_po", "organization_id", "purchase_order_id"),
    )

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_items.id"))
    description: Mapped[str] = mapped_column(String(255))
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.0"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="items")
