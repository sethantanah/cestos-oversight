"""Unified document library and permission-filtered hybrid retrieval."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from pydantic import ValidationError as SchemaError
from sqlalchemy import Text, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_current_active_user, request_storage
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.db.session import get_session
from app.models import User
from app.models.document_library import LibraryDocument as D
from app.services.audit import record_audit
from app.services.document_access import is_document_admin, personal_scope, visible_scope

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentEdit(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=250)
    category: str | None = Field(None, min_length=1, max_length=60)
    tags: list[str] | None = Field(None, max_length=20)
    visibility: Literal["PRIVATE", "PUBLIC", "SUPER_PRIVATE"] | None = None

    @field_validator("title", "category")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Must not be blank")
        return value.strip() if value is not None else value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, tags):
        if tags is None:
            return tags
        cleaned = list(dict.fromkeys(t.strip().lower() for t in tags if t.strip()))
        if any(len(t) > 40 for t in cleaned):
            raise ValueError("Tags must be at most 40 characters")
        return cleaned


def public(row, actor):
    return {
        **{
            k: getattr(row, k)
            for k in (
                "id",
                "title",
                "category",
                "tags",
                "file_name",
                "mime_type",
                "size_bytes",
                "visibility",
                "index_status",
                "index_message",
                "indexed_at",
                "created_at",
                "source_type",
                "source_id",
                "owner_id",
                "employee_id",
            )
        },
        "can_manage": row.owner_id == actor.id or is_document_admin(actor),
    }


async def get_document(session, actor, identifier):
    row = await session.scalar(select(D).where(D.id == identifier, visible_scope(actor)))
    if row is None:
        raise NotFoundError("Document not found")
    return row


def manage(row, actor):
    if row.owner_id != actor.id and not is_document_admin(actor):
        raise ForbiddenError("Only the uploader or a document administrator can change this file")


def audit(session, actor, row, action, previous=None):
    record_audit(
        session,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action=action,
        entity_type="library_document",
        entity_id=row.id,
        old_values=previous,
        new_values={
            "title": row.title,
            "visibility": row.visibility,
            "category": row.category,
            "tags": row.tags,
        },
    )


@router.get("")
async def library(
    q: str = Query("", max_length=500),
    category: str = "",
    tag: str = "",
    view: Literal["all", "for-you", "public", "super-private"] = "for-you",
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    scope = [visible_scope(actor)]
    if view == "for-you":
        scope.append(personal_scope(actor))
    elif view == "public":
        scope.append(D.visibility == "PUBLIC")
    elif view == "super-private":
        scope.append(D.visibility == "SUPER_PRIVATE")
    if category:
        scope.append(D.category == category)
    if tag:
        scope.append(D.tags.contains([tag.lower()]))
    if source_type:
        scope.append(D.source_type == source_type)
    if source_id:
        scope.append(D.source_id == source_id)
    query = select(D).where(*scope).order_by(D.created_at.desc(), D.id.desc())
    search_warning = None
    if q.strip():
        # Metadata + PostgreSQL full text + local semantic retrieval, fused by rank.
        documents = (await session.scalars(query)).all()
        text = func.concat_ws(
            " ",
            D.title,
            D.file_name,
            D.category,
            D.tags.cast(Text),
        )
        search_query = func.websearch_to_tsquery("simple", q)
        rank = func.ts_rank_cd(
            func.to_tsvector("simple", text), search_query
        ) * 2 + func.ts_rank_cd(func.to_tsvector("simple", D.extracted_text), search_query)
        filename_match = or_(
            D.title.icontains(q, autoescape=True), D.file_name.icontains(q, autoescape=True)
        )
        rank = rank + case((filename_match, 2.0), else_=0.0)
        text_match = or_(
            filename_match,
            func.to_tsvector("simple", D.extracted_text).op("@@")(search_query),
            func.to_tsvector("simple", text).op("@@")(search_query),
        )
        lexical = (
            await session.execute(
                select(D.id, rank.label("rank"))
                .where(*scope, text_match)
                .order_by(rank.desc(), D.id)
            )
        ).all()
        fused = {key: 1 / (60 + i) for i, (key, _) in enumerate(lexical, 1)}
        snippets = {}
        try:
            from app.services.document_index import search_vectors

            hits = await run_in_threadpool(search_vectors, documents, q)
            for i, (key, (score, snippet)) in enumerate(
                sorted(hits.items(), key=lambda x: x[1][0], reverse=True), 1
            ):
                if score >= 0.35:
                    fused[key] = fused.get(key, 0) + 1 / (60 + i)
                    snippets[key] = snippet
        except Exception:
            search_warning = (
                "Semantic search is temporarily unavailable. Showing text and filename matches."
            )
        ranked = sorted(
            (d for d in documents if d.id in fused), key=lambda d: (-fused[d.id], str(d.id))
        )
        total = len(ranked)
        items = []
        for row in ranked[(page - 1) * page_size : page * page_size]:
            snippet = snippets.get(row.id)
            if snippet is None:
                words = q.lower().split()
                snippet = next(
                    (c for c in row.chunks if any(w in c["text"].lower() for w in words)), None
                )
            items.append(
                {
                    **public(row, actor),
                    "match": {"text": snippet["text"][:650], "location": snippet["location"]}
                    if snippet
                    else None,
                }
            )
    else:
        total = await session.scalar(select(func.count(D.id)).where(*scope)) or 0
        found = (await session.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
        items = [public(d, actor) for d in found]
    owner_ids = [item["owner_id"] for item in items if item["owner_id"]]
    owners = (
        (
            await session.execute(
                select(User.id, User.first_name, User.last_name).where(
                    User.organization_id == actor.organization_id, User.id.in_(owner_ids)
                )
            )
        ).all()
        if owner_ids
        else []
    )
    owner_names = {
        identifier: " ".join(filter(None, [first, last])) for identifier, first, last in owners
    }
    for item in items:
        item["owner_name"] = owner_names.get(item["owner_id"])
    categories = (
        await session.execute(
            select(D.category, func.count(D.id))
            .where(visible_scope(actor))
            .group_by(D.category)
            .order_by(D.category)
        )
    ).all()
    # Facets are derived only from visible records, including tags and counts.
    tag_rows = (await session.scalars(select(D.tags).where(visible_scope(actor)))).all()
    tags = sorted({t for values in tag_rows for t in values})
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "categories": [{"name": name, "count": count} for name, count in categories],
        "tags": tags,
        "is_admin": is_document_admin(actor),
        "search_warning": search_warning,
    }


@router.post("", status_code=201)
async def upload(
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("General"),
    tags: str = Form(""),
    source_type: str | None = Form(None),
    source_id: uuid.UUID | None = Form(None),
    visibility: Literal["PRIVATE", "PUBLIC"] = Form("PRIVATE"),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
    storage=Depends(request_storage),
):
    try:
        metadata = DocumentEdit(
            title=title.strip() or (file.filename or "Untitled document")[:250],
            category=category.strip() or "General",
            tags=tags.split(","),
        )
    except SchemaError as error:
        raise ValidationError(
            "Check the title, category and tags (up to 20 tags, 40 characters each)"
        ) from error
    if bool(source_type) != bool(source_id):
        raise ValidationError("Both source type and source ID are required to link a document")
    if source_type:
        if source_type not in {"pm_job_card", "breakdown_job_card", "hse_incident"}:
            raise ValidationError("Unsupported linked document type")
        if source_type == "hse_incident":
            from app.models.maintenance_hse import HseIncident
            linked_model = HseIncident
        else:
            from app.models.operational_logs import BreakdownJobCard, PMJobCard
            linked_model = PMJobCard if source_type == "pm_job_card" else BreakdownJobCard
        linked_record = await session.scalar(select(linked_model.id).where(
            linked_model.id == source_id,
            linked_model.organization_id == actor.organization_id,
            linked_model.archived_at.is_(None),
        ))
        if linked_record is None:
            raise NotFoundError("Maintenance job card not found")
        visibility = "PUBLIC"
    data = await file.read(storage.max_bytes + 1)
    if not data:
        raise ValidationError("Choose a non-empty file")
    try:
        stored = await run_in_threadpool(
            storage.save,
            f"documents/{actor.organization_id}",
            data,
            file.filename or "document",
            "application/octet-stream",
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error
    identifier = uuid.uuid4()
    row = D(
        id=identifier,
        organization_id=actor.organization_id,
        source_type=source_type or "library",
        source_id=source_id or identifier,
        title=metadata.title,
        category=metadata.category,
        tags=metadata.tags,
        storage_path=stored.relative_path,
        file_name=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        owner_id=actor.id,
        visibility=visibility,
    )
    try:
        session.add(row)
        await session.flush()
        audit(session, actor, row, "document.uploaded")
        await session.commit()
    except Exception:
        await session.rollback()
        await run_in_threadpool(storage.delete, stored.relative_path)
        raise
    return public(row, actor)


@router.get("/{identifier}")
async def get_document_details(
    identifier: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    row = await get_document(session, actor, identifier)
    return public(row, actor)


@router.patch("/{identifier}")
async def edit(
    identifier: uuid.UUID,
    body: DocumentEdit,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    row = await get_document(session, actor, identifier)
    manage(row, actor)
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    previous = {k: getattr(row, k) for k in data}
    if data.get("visibility") == "SUPER_PRIVATE":
        if not is_document_admin(actor):
            raise ForbiddenError("Only document administrators can mark a file Super Private")
        row.private_to_id = actor.id
    elif "visibility" in data:
        row.private_to_id = None
    for key, value in data.items():
        setattr(row, key, value)
    audit(session, actor, row, "document.updated", previous)
    await session.commit()
    return public(row, actor)


@router.get("/{identifier}/download")
async def download(
    identifier: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
    storage=Depends(request_storage),
):
    row = await get_document(session, actor, identifier)
    path = await run_in_threadpool(storage.resolve, row.storage_path)
    if not path.is_file():
        raise NotFoundError("File is unavailable")
    audit(session, actor, row, "document.downloaded")
    await session.commit()
    return FileResponse(
        path,
        filename=row.file_name,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{identifier}/view")
@router.get("/{identifier}/view/{filename:path}")
@router.get("/{identifier}/file/{filename:path}")
async def view_document_file(
    identifier: uuid.UUID,
    filename: str | None = None,
    disposition: str = Query("inline"),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
    storage=Depends(request_storage),
):
    row = await get_document(session, actor, identifier)
    path = await run_in_threadpool(storage.resolve, row.storage_path)
    if not path.is_file():
        raise NotFoundError("File is unavailable")
    
    import mimetypes
    guessed_type, _ = mimetypes.guess_type(row.file_name)
    media_type = row.mime_type or guessed_type or "application/pdf"
    if media_type == "application/octet-stream" and guessed_type:
        media_type = guessed_type

    audit(session, actor, row, "document.viewed")
    await session.commit()
    
    headers = {
        "Content-Disposition": f'inline; filename="{row.file_name}"',
        "Cache-Control": "private, max-age=3600",
    }
    return FileResponse(
        path,
        media_type=media_type,
        headers=headers,
    )


@router.get("/{identifier}/text")
async def document_text(
    identifier: uuid.UUID,
    page: int = Query(1, ge=1),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    row = await get_document(session, actor, identifier)
    return {
        "id": row.id,
        "title": row.title,
        "status": row.index_status,
        "total": len(row.chunks),
        "chunks": row.chunks[(page - 1) * 20 : page * 20],
    }


@router.post("/{identifier}/reindex", status_code=202)
async def reindex(
    identifier: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    row = await get_document(session, actor, identifier)
    manage(row, actor)
    row.index_status = "PENDING"
    row.index_message = None
    audit(session, actor, row, "document.reindex_requested")
    await session.commit()
    return {"status": "PENDING"}
