"""Public response contracts for document utility endpoints."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class DocumentTextSection(BaseModel):
    location: str
    text: str


class DocumentTextExtractionResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "examples": [{
            "filename": "supplier-invoice.pdf",
            "content_type": "application/pdf",
            "text": "[Page 1]\nInvoice number: INV-1042\nTotal: USD 250.00",
            "sections": [{
                "location": "Page 1",
                "text": "Invoice number: INV-1042\nTotal: USD 250.00",
            }],
            "warning": None,
        }]
    })

    filename: str
    content_type: str | None
    text: str
    sections: list[DocumentTextSection]
    warning: str | None


class DocumentSchemaExtractionResponse(BaseModel):
    """`data` is dynamic and conforms to the JSON Schema sent with the request."""

    model_config = ConfigDict(json_schema_extra={
        "examples": [{
            "filename": "supplier-invoice.pdf",
            "content_type": "application/pdf",
            "document_type": "invoice",
            "tags": ["invoice"],
            "data": {
                "invoice_number": "INV-1042",
                "supplier": "Example Supplier",
                "total": 250.0,
            },
            "warning": None,
        }]
    })

    filename: str
    content_type: str | None
    document_type: Literal["invoice", "receipt", "quotation", "other"]
    tags: list[Literal["invoice", "receipt", "quotation", "other"]]
    data: Any
    warning: str | None
