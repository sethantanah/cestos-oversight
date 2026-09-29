"""Authenticated document utilities for OCR and schema-guided extraction."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.document_utils import (
    DocumentSchemaExtractionResponse,
    DocumentTextExtractionResponse,
)
from app.services.document_utilities import (
    MAX_DOCUMENT_BYTES,
    MAX_SCHEMA_BYTES,
    extract_document,
    fill_document_schema,
)

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/extract-text",
    response_model=DocumentTextExtractionResponse,
    summary="Extract text from a document",
    description=(
        "Accepts one multipart file (maximum 10 MB). Supports PDF, PNG, JPEG, TIFF, BMP, "
        "WebP, DOCX, XLSX, XLS, PPTX, ODT, ODS, ODP, RTF, TXT, CSV, HTML, HTM, and XML. "
        "Scanned PDF pages and image uploads are passed through OCR. Returns extracted text "
        "and per-section text. PDF extraction is bounded to 300 pages and 2 million characters. "
        "`warning` is null when extraction was not truncated."
    ),
    response_description="Extracted document text, section locations, and any extraction warning.",
    responses={
        413: {"description": "The uploaded file is larger than 10 MB."},
        422: {
            "description": (
                "The file is empty, unsupported, unreadable, or contains no readable text."
            )
        },
    },
)
async def extract_text_from_file(
    file: Annotated[
        UploadFile,
        File(description="One supported document or image file; maximum size is 10 MB."),
    ],
    _actor: Annotated[User, Depends(get_current_active_user)],
) -> DocumentTextExtractionResponse:
    """Extract text from text-based files, scanned PDFs, and image uploads."""
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="The file exceeds the 10 MB extraction limit.")
    try:
        result = await run_in_threadpool(extract_document, data, file.filename or "upload")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DocumentTextExtractionResponse(**{
        "filename": file.filename or "upload",
        "content_type": file.content_type,
        **result,
    })


@router.post(
    "/extract-schema",
    response_model=DocumentSchemaExtractionResponse,
    summary="Extract document data into a JSON Schema",
    description=(
        "Accepts a multipart file (maximum 10 MB) and `json_schema`, a string containing a "
        "JSON Schema object (maximum 32 KB). The extracted document text is sent to the configured "
        "OpenAI model, which returns values matching the supplied schema and classifies the file "
        "as invoice, receipt, quotation, or other. `$ref` is not supported; inline subschemas. "
        "The response `data` value has the shape defined by the submitted schema."
    ),
    response_description=(
        "The schema-populated `data`, a document classification and matching tag, filename, "
        "content type, and any extraction warning."
    ),
    responses={
        413: {"description": "The file exceeds 10 MB or the JSON Schema exceeds 32 KB."},
        422: {
            "description": (
                "The file or JSON Schema is invalid, unreadable, or the result does not "
                "match the schema."
            )
        },
        503: {
            "description": "AI document extraction is not configured or temporarily unavailable."
        },
    },
)
async def extract_file_to_schema(
    file: Annotated[
        UploadFile,
        File(description="One supported document or image file; maximum size is 10 MB."),
    ],
    json_schema: Annotated[
        str,
        Form(
            description="A JSON-encoded JSON Schema object; maximum size is 32 KB.",
            examples=[
                '{"type":"object","properties":{"invoice_number":{"type":"string"}},'
                '"required":["invoice_number"]}'
            ],
        ),
    ],
    request: Request,
    _actor: Annotated[User, Depends(get_current_active_user)],
) -> DocumentSchemaExtractionResponse:
    """Extract text, classify the document, and fill the caller's JSON schema with AI."""
    if len(json_schema.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise HTTPException(status_code=413, detail="The JSON schema exceeds the 32 KB limit.")
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="The file exceeds the 10 MB extraction limit.")
    try:
        result = await run_in_threadpool(
            fill_document_schema,
            data,
            file.filename or "upload",
            json_schema,
            request.app.state.settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DocumentSchemaExtractionResponse(**{**result, "content_type": file.content_type})
