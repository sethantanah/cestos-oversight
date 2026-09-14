"""Transactional catalog registration for every document-bearing source model."""

import uuid
from pathlib import PurePosixPath

from sqlalchemy import Text, and_, event, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import AssetDocument, AuditLog, EmployeeDocument, EmployeeResume
from app.models.asset_records import AssetMedia
from app.models.document_library import LibraryDocument as D
from app.models.employee import LeaveRequest
from app.models.operational_logs import AssetLogFile, ProjectRecord
from app.models.project_report import ProjectReport
from app.services.document_access import visible_scope

SOURCES = {
    EmployeeDocument: ("storage_path", "People"),
    EmployeeResume: ("storage_path", "People"),
    AssetDocument: ("storage_path", "Equipment"),
    AssetMedia: ("storage_path", "Equipment"),
    AssetLogFile: ("storage_path", "Equipment"),
    ProjectRecord: ("storage_path", "Projects"),
    ProjectReport: ("storage_path", "Projects"),
    LeaveRequest: ("attachment_url", "Leave"),
}
FILE_MODELS = (
    EmployeeDocument,
    EmployeeResume,
    AssetDocument,
    AssetMedia,
    AssetLogFile,
    ProjectRecord,
)


def source_values(row, actor_id=None):
    model = type(row)
    path_key, category = SOURCES[model]
    path = getattr(row, path_key, None)
    if not path or path.startswith(("https:", "http:")):
        return None
    if isinstance(row, AssetMedia) and row.media_type in {"PHOTO", "VIDEO"}:
        return None
    if isinstance(row, AssetLogFile) and row.log_type in {"STORE", "ITEM"}:
        category = "Inventory"
    return dict(
        id=uuid.uuid4(),
        organization_id=row.organization_id,
        source_type=row.__tablename__,
        source_id=row.id,
        title=(getattr(row, "title", None) or getattr(row, "file_name", None) or "Leave letter")[
            :250
        ],
        category=category,
        tags=[],
        storage_path=path,
        file_name=(getattr(row, "file_name", None) or PurePosixPath(path).name)[:255],
        mime_type=getattr(row, "mime_type", None) or "application/octet-stream",
        size_bytes=getattr(row, "size_bytes", None) or getattr(row, "file_size", None) or 0,
        owner_id=actor_id
        or getattr(row, "uploaded_by_id", None)
        or getattr(row, "created_by_id", None),
        employee_id=getattr(row, "employee_id", None),
        visibility="PRIVATE",
        is_active=getattr(row, "is_active", True),
        index_status="PENDING",
        extracted_text="",
        chunks=[],
    )


@event.listens_for(Session, "before_flush")
def remember_sources(session, context, instances):
    candidates = [r for r in session.new.union(session.dirty) if type(r) in SOURCES]
    for row in candidates:
        if row.id is None:
            row.id = uuid.uuid4()
    session.info["document_sources"] = candidates
    session.info["document_deleted"] = [r for r in session.deleted if type(r) in SOURCES]


@event.listens_for(Session, "after_flush_postexec")
def register_sources(session, context):
    connection = session.connection()
    actor = session.info.get("document_actor")
    for row in session.info.pop("document_sources", []):
        values = source_values(row, actor.id if actor else None)
        if values is None:
            continue
        stmt = insert(D).values(**values)
        # Metadata changes do not discard user tags or change the uploader/visibility.
        changed_file = D.storage_path != stmt.excluded.storage_path
        from sqlalchemy import case

        connection.execute(
            stmt.on_conflict_do_update(
                constraint="uq_library_source",
                set_={
                    "storage_path": stmt.excluded.storage_path,
                    "file_name": stmt.excluded.file_name,
                    "mime_type": stmt.excluded.mime_type,
                    "size_bytes": stmt.excluded.size_bytes,
                    "is_active": stmt.excluded.is_active,
                    "index_status": case((changed_file, "PENDING"), else_=D.index_status),
                    "vector_path": case((changed_file, None), else_=D.vector_path),
                    "extracted_text": case((changed_file, ""), else_=D.extracted_text),
                    "chunks": case((changed_file, stmt.excluded.chunks), else_=D.chunks),
                },
            )
        )
    for row in session.info.pop("document_deleted", []):
        connection.execute(
            D.__table__.update()
            .where(
                D.source_type == row.__tablename__,
                D.source_id == row.id,
                D.organization_id == row.organization_id,
            )
            .values(is_active=False)
        )


@event.listens_for(Session, "do_orm_execute")
def protect_source_documents(state):
    actor = state.session.info.get("document_actor")
    if not actor or not state.is_select or state.execution_options.get("document_internal"):
        return
    linked_audit = and_(
        D.organization_id == AuditLog.organization_id,
        or_(
            D.id == AuditLog.entity_id,
            D.source_id == AuditLog.entity_id,
            and_(
                D.source_type == "project_reports",
                or_(
                    D.source_id.cast(Text) == AuditLog.new_values["report_id"].astext,
                    and_(
                        AuditLog.action == "project.report_updated",
                        D.source_id.cast(Text) == AuditLog.new_values["id"].astext,
                    ),
                ),
            ),
        ),
    )
    state.statement = state.statement.options(
        with_loader_criteria(
            AuditLog,
            or_(
                ~exists(select(D.id).where(linked_audit)),
                exists(select(D.id).where(linked_audit, visible_scope(actor))),
            ),
            include_aliases=True,
        )
    )
    for model in FILE_MODELS:
        protected = exists(
            select(D.id).where(
                D.source_type == model.__tablename__,
                D.source_id == model.id,
                visible_scope(actor),
            )
        )
        exception = model.storage_path.is_(None)
        if model is AssetMedia:
            exception = or_(exception, model.media_type.in_(["PHOTO", "VIDEO"]))
        if model is ProjectRecord:
            exception = or_(exception, model.record_type != "FILE")
        state.statement = state.statement.options(
            with_loader_criteria(
                model,
                or_(exception, protected),
                include_aliases=True,
            )
        )


async def backfill_registry(session):
    """Idempotent import, including existing uploads; never infer an uploader from an editor."""
    try:
        logs = (
            await session.execute(
                select(AuditLog.organization_id, AuditLog.entity_id, AuditLog.actor_user_id)
                .where(
                    AuditLog.action.in_(
                        ["employee.document_added", "employee.resume_uploaded", "asset.document_added"]
                    )
                )
                .order_by(AuditLog.created_at.desc())
            )
        ).all()
        uploaders = {(org, entity): actor for org, entity, actor in logs}
        for model in SOURCES:
            source_rows = (
                await session.scalars(select(model).execution_options(document_internal=True))
            ).all()
            for row in source_rows:
                values = source_values(row)
                if values and not values["owner_id"]:
                    values["owner_id"] = uploaders.get((row.organization_id, row.id))
                if values:
                    await session.execute(
                        insert(D)
                        .values(**values)
                        .on_conflict_do_nothing(constraint="uq_library_source")
                    )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        import structlog

        structlog.get_logger().warning("backfill_registry_failed", error=str(exc))
