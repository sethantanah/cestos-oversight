import json
from types import SimpleNamespace

import pytest

from app.services import document_utilities


def test_extract_document_uses_shared_pdf_and_ocr_pipeline(monkeypatch):
    observed = {}

    def fake_extract(path, filename):
        observed["filename"] = filename
        observed["contents"] = path.read_bytes()
        return ([{"location": "Page 1", "text": "Invoice total: $42.00"}], None)

    monkeypatch.setattr(document_utilities, "extract", fake_extract)
    result = document_utilities.extract_document(b"pdf bytes", "invoice.pdf")

    assert result["text"] == "[Page 1]\nInvoice total: $42.00"
    assert result["warning"] is None
    assert observed == {"filename": "invoice.pdf", "contents": b"pdf bytes"}


def test_extract_document_rejects_empty_and_unsupported_files():
    with pytest.raises(ValueError, match="empty"):
        document_utilities.extract_document(b"", "invoice.pdf")
    with pytest.raises(ValueError, match="Upload a PDF"):
        document_utilities.extract_document(b"data", "invoice.exe")


def test_validate_schema_value_reports_missing_and_invalid_values():
    schema = {
        "type": "object",
        "required": ["invoice_number", "total"],
        "properties": {
            "invoice_number": {"type": "string", "minLength": 1},
            "total": {"type": "number", "minimum": 0},
        },
        "additionalProperties": False,
    }
    errors = document_utilities.validate_schema_value(
        {"invoice_number": "", "total": -1, "extra": True}, schema
    )
    assert len(errors) == 3


def test_fill_document_schema_returns_classification_tag_and_schema_data(monkeypatch):
    schema = {
        "type": "object",
        "required": ["invoice_number"],
        "properties": {"invoice_number": {"type": "string"}},
    }
    monkeypatch.setattr(
        document_utilities,
        "extract_document",
        lambda *_: {"text": "Invoice No. INV-100", "sections": [], "warning": None},
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            completion = {
                "document_type": "invoice",
                "data": {"invoice_number": "INV-100"},
            }
            result = {"choices": [{"message": {"content": json.dumps(completion)}}]}
            return json.dumps(result).encode()

    monkeypatch.setattr(
        document_utilities.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    settings = SimpleNamespace(openai_api_key="test-key", openai_model="gpt-4o-mini")

    result = document_utilities.fill_document_schema(
        b"file", "invoice.pdf", json.dumps(schema), settings
    )

    assert result["document_type"] == "invoice"
    assert result["tags"] == ["invoice"]
    assert result["data"] == {"invoice_number": "INV-100"}
