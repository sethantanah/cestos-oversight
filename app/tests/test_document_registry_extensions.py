import pytest
from sqlalchemy import select
from app.models.document_library import LibraryDocument
from app.models.procurement import PurchaseOrder
from app.models.operational_logs import FuelDelivery, OperationalExpense, OperationalExpensePayment
from app.services.document_registry import source_values

pytestmark = pytest.mark.asyncio


def test_source_values_purchase_order(dummy_uuid=None):
    import uuid
    org_id = uuid.uuid4()
    po = PurchaseOrder(
        id=uuid.uuid4(),
        organization_id=org_id,
        po_number="PO-2026-0001",
        attachment_path="documents/org/po-quote.pdf",
        attachment_file_name="quote.pdf",
    )
    vals = source_values(po)
    assert len(vals) == 1
    assert vals[0]["source_type"] == "purchase_orders"
    assert vals[0]["category"] == "Procurement"
    assert vals[0]["storage_path"] == "documents/org/po-quote.pdf"
    assert vals[0]["index_status"] == "PENDING"


def test_source_values_operational_expense():
    import uuid
    org_id = uuid.uuid4()
    exp = OperationalExpense(
        id=uuid.uuid4(),
        organization_id=org_id,
        expense_number="EXP-2026-001",
        invoice_path="documents/org/inv.pdf",
        invoice_name="inv.pdf",
        receipt_path="documents/org/rec.pdf",
        receipt_name="rec.pdf",
    )
    vals = source_values(exp)
    assert len(vals) == 2
    types = {v["source_type"] for v in vals}
    assert types == {"operational_expenses_invoice", "operational_expenses_receipt"}
    for v in vals:
        assert v["category"] == "Finance"
        assert v["index_status"] == "PENDING"


def test_source_values_fuel_delivery():
    import uuid
    org_id = uuid.uuid4()
    fuel = FuelDelivery(
        id=uuid.uuid4(),
        organization_id=org_id,
        reference_number="FD-99",
        receipt_path="documents/org/fuel.pdf",
        receipt_file_name="fuel.pdf",
    )
    vals = source_values(fuel)
    assert len(vals) == 1
    assert vals[0]["source_type"] == "fuel_deliveries"
    assert vals[0]["category"] == "Field Operations"
    assert vals[0]["index_status"] == "PENDING"
