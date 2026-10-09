"""Revision-checked, idempotent workbook saves. Each accepted edit retains the prior file."""
import hashlib
import json
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from app.core.dependencies import get_current_active_user, request_storage
from app.core.exceptions import ConflictError, ForbiddenError, ValidationError
from app.db.session import get_session
from app.models import User
from app.models.document_library import LibraryDocument as D
from app.api.v1.endpoints.documents import audit

router = APIRouter(prefix='/workbook-sync', tags=['Workbook sync'])

class WorkbookSave(BaseModel):
    workbook: dict
    operation_id: uuid.UUID
    base_version: uuid.UUID | None = None

async def lock_workbook(session, organization_id, workbook_id):
    # A transaction-scoped lock also serializes creation when no document exists yet.
    key = int.from_bytes(hashlib.sha256(f'{organization_id}:{workbook_id}'.encode()).digest()[:8], 'big', signed=True)
    await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})

def payload_bytes(book):
    try:
        uuid.UUID(book.get('id', ''))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Workbook needs a valid unique ID')
    if book.get('version') != 1 or not isinstance(book.get('name'), str) or not book['name'].strip() or len(book['name']) > 250:
        raise ValidationError('Invalid workbook name or version')
    sheets = book.get('sheets')
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= 200:
        raise ValidationError('Invalid workbook sheets')
    ids = set()
    for sheet in sheets:
        if not isinstance(sheet, dict) or not isinstance(sheet.get('id'), str) or sheet['id'] in ids:
            raise ValidationError('Invalid or duplicate sheet ID')
        ids.add(sheet['id'])
        rows, widths, heights = sheet.get('cells'), sheet.get('widths'), sheet.get('heights')
        if not isinstance(rows,list) or not 1 <= len(rows) <= 2000 or not isinstance(widths,list) or not 1 <= len(widths) <= 100 or not isinstance(heights,list) or len(heights) != len(rows):
            raise ValidationError('Invalid workbook dimensions')
        if any(not isinstance(row,list) or len(row) != len(widths) or any(not isinstance(v,str) or len(v)>32767 for v in row) for row in rows):
            raise ValidationError('Invalid workbook cells')
    try:
        data = json.dumps(book, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    except (ValueError, TypeError):
        raise ValidationError('Invalid workbook data')
    if len(data) > 50_000_000:
        raise ValidationError('Workbook exceeds the 50 MB sync limit; keep an exported backup')
    return data

def check_revision(latest, base_version):
    if latest is not None and not latest.is_active:
        raise ConflictError('This workbook was deleted on the server. Save your local work as a new copy.')
    if (str(latest.id) if latest else None) != (str(base_version) if base_version else None):
        raise ConflictError('Another device saved a newer version. Your local copy is safe. Review both versions or save yours as a new copy.')

@router.post('')
async def save_workbook(payload: WorkbookSave, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session), storage=Depends(request_storage)):
    book = payload.workbook
    data = payload_bytes(book)
    digest = hashlib.sha256(data).hexdigest()
    tag = 'wb-' + book['id']
    await lock_workbook(session, actor.organization_id, book['id'])
    previous = await session.scalar(select(D).where(D.organization_id == actor.organization_id, D.source_type == 'workbook-sync', D.source_id == payload.operation_id))
    if previous:
        if previous.owner_id != actor.id or tag not in previous.tags or previous.content_hash != digest:
            raise ConflictError('This save identifier already belongs to different content')
        if not previous.is_active:
            raise ConflictError('The saved workbook was deleted. Save a new copy instead.')
        return {'version': str(previous.id), 'operation_id': str(payload.operation_id)}
    latest = await session.scalar(select(D).where(D.organization_id == actor.organization_id, D.category == 'Field Workbooks', D.tags.contains([tag])).order_by(D.created_at.desc(), D.id.desc()).limit(1))
    if latest and latest.owner_id != actor.id:
        raise ForbiddenError('Save a personal copy to edit a workbook owned by another user')
    check_revision(latest, payload.base_version)
    try:
        stored = await run_in_threadpool(storage.save, f'documents/{actor.organization_id}', data, f'{book["id"]}.cestos.json', 'application/json')
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    row = D(id=uuid.uuid4(), organization_id=actor.organization_id, source_type='workbook-sync', source_id=payload.operation_id, owner_id=actor.id,
            title=book['name'], category='Field Workbooks', tags=[tag, 'workbook-template' if book.get('template') else 'field-workbook'],
            storage_path=stored.relative_path, file_name=stored.filename, mime_type=stored.mime_type, size_bytes=stored.size_bytes,
            visibility='PRIVATE', content_hash=digest, created_at=func.clock_timestamp())
    try:
        session.add(row)
        await session.flush()
        audit(session, actor, row, 'workbook.synced')
        await session.commit()
    except Exception:
        await session.rollback()
        await run_in_threadpool(storage.delete, stored.relative_path)
        raise
    return {'version': str(row.id), 'operation_id': str(payload.operation_id)}
