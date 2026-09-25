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
from app.models.operational_logs import (
    AssetLogFile,
    FuelDelivery,
    OperationalExpense,
    OperationalExpensePayment,
    ProjectRecord,
)
from app.models.procurement import PurchaseOrder
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
    PurchaseOrder: ("attachment_path", "Procurement"),
    FuelDelivery: ("receipt_path", "Field Operations"),
    OperationalExpensePayment: ("receipt_path", "Finance"),
    OperationalExpense: [
        (
            "invoice_path",
            "Finance",
            "invoice_name",
            "invoice_mime_type",
            "invoice_size_bytes",
            "Invoice",
            "operational_expenses_invoice",
        ),
        (
            "receipt_path",
            "Finance",
            "receipt_name",
            "receipt_mime_type",
            "receipt_size_bytes",
            "Receipt",
            "operational_expenses_receipt",
        ),
    ],
}
FILE_MODELS = (
    EmployeeDocument,
    EmployeeResume,
    AssetDocument,
    AssetMedia,
    AssetLogFile,
    ProjectRecord,
    PurchaseOrder,
    FuelDelivery,
    OperationalExpensePayment,
    OperationalExpense,
)


def source_values(row, actor_id=None):
    model = type(row)
    if model not in SOURCES:
        return []
    spec = SOURCES[model]
    spec_list = spec if isinstance(spec, list) else [spec]
    results = []

    for spec_item in spec_list:
        path_key = spec_item[0]
        category = spec_item[1]
        path = getattr(row, path_key, None)
        if not path or path.startswith(("https:", "http:")):
            continue
        if isinstance(row, AssetMedia) and row.media_type in {"PHOTO", "VIDEO"}:
            continue
        if isinstance(row, AssetLogFile) and row.log_type in {"STORE", "ITEM"}:
            category = "Inventory"

        file_name_attr = spec_item[2] if len(spec_item) > 2 else "file_name"
        mime_type_attr = spec_item[3] if len(spec_item) > 3 else "mime_type"
        size_bytes_attr = spec_item[4] if len(spec_item) > 4 else "size_bytes"
        label_suffix = spec_item[5] if len(spec_item) > 5 else None
        custom_source_type = spec_item[6] if len(spec_item) > 6 else row.__tablename__

        raw_title = (
            getattr(row, "title", None)
            or getattr(row, "po_number", None)
            or getattr(row, "expense_number", None)
            or getattr(row, "reference_number", None)
            or getattr(row, "reference", None)
            or getattr(row, file_name_attr, None)
            or getattr(row, "file_name", None)
            or "Document"
        )
        if label_suffix:
            title = f"{raw_title} ({label_suffix})"
        else:
            title = str(raw_title)

        file_name = (
            getattr(row, file_name_attr, None)
            or getattr(row, "file_name", None)
            or PurePosixPath(path).name
        )
        mime_type = getattr(row, mime_type_attr, None) or getattr(row, "mime_type", None) or "application/octet-stream"
        size_bytes = getattr(row, size_bytes_attr, None) or getattr(row, "size_bytes", None) or getattr(row, "file_size", None) or 0

        results.append(
            dict(
                id=uuid.uuid4(),
                organization_id=row.organization_id,
                source_type=custom_source_type,
                source_id=row.id,
                title=str(title)[:250],
                category=category,
                tags=[],
                storage_path=path,
                file_name=str(file_name)[:255],
                mime_type=str(mime_type)[:150],
                size_bytes=int(size_bytes or 0),
                owner_id=actor_id
                or getattr(row, "uploaded_by_id", None)
                or getattr(row, "created_by_id", None)
                or getattr(row, "submitted_by_id", None)
                or getattr(row, "paid_by_id", None),
                employee_id=getattr(row, "employee_id", None),
                visibility="PRIVATE",
                is_active=getattr(row, "is_active", True),
                index_status="PENDING",
                extracted_text="",
                chunks=[],
            )
        )
    return results


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
        for values in source_values(row, actor.id if actor else None):
            stmt = insert(D).values(**values)
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
        source_types = [model.__tablename__]
        if model is OperationalExpense:
            source_types = ["operational_expenses_invoice", "operational_expenses_receipt"]
        protected = exists(
            select(D.id).where(
                D.source_type.in_(source_types),
                D.source_id == model.id,
                visible_scope(actor),
            )
        )
        if hasattr(model, "storage_path"):
            exception = model.storage_path.is_(None)
        elif hasattr(model, "attachment_path"):
            exception = model.attachment_path.is_(None)
        elif hasattr(model, "attachment_url"):
            exception = model.attachment_url.is_(None)
        elif model is OperationalExpense:
            exception = and_(model.invoice_path.is_(None), model.receipt_path.is_(None))
        elif hasattr(model, "receipt_path"):
            exception = model.receipt_path.is_(None)
        else:
            exception = True

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
                        [
                            "employee.document_added",
                            "employee.resume_uploaded",
                            "asset.document_added",
                            "procurement.attachment_uploaded",
                            "operational_expenses.receipt_uploaded",
                            "operational_expenses.payment_receipt_uploaded",
                            "field_portal.fuel_delivery_receipt_uploaded",
                        ]
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
                for values in source_values(row):
                    if not values["owner_id"]:
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

