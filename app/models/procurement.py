import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
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
    WAITING_APPROVAL = "WAITING_APPROVAL"
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
    category: Mapped[str | None] = mapped_column(String(100))
    # The procurement migration stores status as VARCHAR(30). Keep the ORM
    # aligned with that schema instead of asking PostgreSQL for an undeclared
    # native enum type (`po_status`). StrEnum values remain string-compatible.
    status: Mapped[PoStatus] = mapped_column(String(30), default=PoStatus.DRAFT)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.0"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(Text)
    attachment_file_name: Mapped[str | None] = mapped_column(String(255))
    attachment_mime_type: Mapped[str | None] = mapped_column(String(150))
    attachment_size_bytes: Mapped[int | None]
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped["FuelSupplier"] = relationship("FuelSupplier", lazy="selectin")
    created_by_user: Mapped["User | None"] = relationship(
        "User", foreign_keys="PurchaseOrder.created_by_id", lazy="selectin"
    )
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        "PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def supplier_name(self) -> str | None:
        return self.supplier.name if self.supplier else None

    @property
    def created_by_name(self) -> str | None:
        if not self.created_by_user:
            return None
        return " ".join(filter(None, (self.created_by_user.first_name, self.created_by_user.last_name))) or None


class PurchaseOrderItem(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        Index("ix_po_items_org_po", "organization_id", "purchase_order_id"),
    )

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_items.id"))
    item_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(255))
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.0"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="items")
