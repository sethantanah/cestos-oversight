import json
from types import SimpleNamespace

from app.services import line_item_extraction


def test_normalize_extracted_line_item_to_purchase_schema():
    result = line_item_extraction._normalize_result(json.dumps({
        "supplier_name": "Example Supplier",
        "currency": "usd",
        "total_amount": 25.5,
        "items": [{
            "item_name": "Filter",
            "description": "Oil filter",
            "quantity": "3",
            "unit_price": "8.50",
        }],
    }))

    assert result["supplier_name"] == "Example Supplier"
    assert result["currency"] == "USD"
    assert result["total_amount"] == 25.5
    assert result["items"] == [{
        "item_name": "Filter",
        "description": "Oil filter",
        "quantity": 3.0,
        "unit_price": 8.5,
    }]


def test_extract_uses_small_model_and_returns_manual_review_draft(monkeypatch):
    monkeypatch.setattr(line_item_extraction, "_extract_text", lambda _data, _name: "Invoice text")
    monkeypatch.setattr(
        line_item_extraction,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key"),
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps({
                "items": [{"name": "Grease", "quantity": 2, "unit_cost": 5}],
                "total_amount": 10,
            })}}]}).encode()

    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(line_item_extraction.urllib.request, "urlopen", fake_urlopen)
    result = line_item_extraction.extract_line_items(b"document", "invoice.pdf", "expense")

    assert captured["payload"]["model"] == "gpt-4o-mini"
    assert captured["timeout"] == 30
    assert result["items"][0]["item_name"] == "Grease"
    assert result["items"][0]["unit_price"] == 5
    assert "Review" in result["message"]


def test_reject_unsupported_document_extension():
    try:
        line_item_extraction._extract_text(b"data", "archive.zip")
    except ValueError as error:
        assert "Upload a PDF" in str(error)
    else:
        raise AssertionError("Unsupported file type should be rejected")
