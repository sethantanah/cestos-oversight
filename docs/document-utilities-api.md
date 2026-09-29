# Document utility API

Both endpoints are under `/api/v1/utils`. They require an active user bearer token and accept multipart form data. Uploaded files are processed in memory/temp storage and are not persisted by these endpoints.

## `POST /api/v1/utils/extract-text`

Extracts text from a supported document. PDF pages use embedded text when available and OCR when a page appears scanned. Image files use OCR. The maximum file size is 10 MB. PDF extraction is bounded to 300 pages and 2 million characters; `warning` reports when extraction was partial.

Supported filename extensions: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp`, `.docx`, `.xlsx`, `.xls`, `.pptx`, `.odt`, `.ods`, `.odp`, `.rtf`, `.txt`, `.csv`, `.html`, `.htm`, and `.xml`.

Request body (`multipart/form-data`):

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | binary file | Yes | One supported document or image, up to 10 MB. |

Example:

```bash
curl -X POST "$API_BASE/api/v1/utils/extract-text" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@supplier-invoice.pdf"
```

Success response (`200`):

```json
{
  "filename": "supplier-invoice.pdf",
  "content_type": "application/pdf",
  "text": "[Page 1]\nInvoice number: INV-1042\nTotal: USD 250.00",
  "sections": [
    {
      "location": "Page 1",
      "text": "Invoice number: INV-1042\nTotal: USD 250.00"
    }
  ],
  "warning": null
}
```

`sections[].location` identifies where text was found, such as a PDF page, document, spreadsheet sheet, or presentation slide. `warning` is either `null` or explains partial extraction/truncation.

## `POST /api/v1/utils/extract-schema`

Extracts text, classifies the document, and asks the configured OpenAI model to populate a caller-provided JSON Schema. The response `data` matches the schema supplied in the same request. The file limit is 10 MB and the UTF-8 schema string limit is 32 KB.

Request body (`multipart/form-data`):

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | binary file | Yes | One supported document or image, up to 10 MB. |
| `json_schema` | string | Yes | A JSON-encoded JSON Schema object, up to 32 KB. Inline referenced schemas; `$ref` is not supported. |

Example schema submitted as the `json_schema` form value:

```json
{
  "type": "object",
  "properties": {
    "invoice_number": { "type": "string" },
    "supplier": { "type": "string" },
    "total": { "type": "number", "minimum": 0 },
    "currency": { "type": "string", "enum": ["USD", "EUR", "GBP"] }
  },
  "required": ["invoice_number", "supplier", "total"],
  "additionalProperties": false
}
```

Example request:

```bash
curl -X POST "$API_BASE/api/v1/utils/extract-schema" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@supplier-invoice.pdf" \
  -F 'json_schema={"type":"object","properties":{"invoice_number":{"type":"string"},"supplier":{"type":"string"},"total":{"type":"number"}},"required":["invoice_number","supplier","total"],"additionalProperties":false}'
```

Success response (`200`):

```json
{
  "filename": "supplier-invoice.pdf",
  "content_type": "application/pdf",
  "document_type": "invoice",
  "tags": ["invoice"],
  "data": {
    "invoice_number": "INV-1042",
    "supplier": "Example Supplier",
    "total": 250.0,
    "currency": "USD"
  },
  "warning": null
}
```

`document_type` is one of `invoice`, `receipt`, `quotation`, or `other`; `tags` contains that same single classification. `data` is dynamic and has the structure of the request's `json_schema`. Unknown source values are not intended to be invented by the model. `warning` explains if only part of a long document was sent for AI extraction or if text extraction was partial. AI input is limited to the first 60,000 extracted characters.

## Errors

The documented error statuses use the standard API error envelope:

```json
{
  "error": {
    "code": "HTTP_ERROR",
    "message": "The file exceeds the 10 MB extraction limit."
  }
}
```

| Status | Meaning |
| --- | --- |
| `401` | Missing, invalid, or inactive user authentication. |
| `413` | File is over 10 MB or schema text is over 32 KB. |
| `422` | Unsupported, empty, unreadable file; invalid schema JSON; unsupported `$ref`; or extracted result fails schema validation. |
| `503` | AI extraction is not configured or the model request failed. |
