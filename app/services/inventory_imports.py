"""Validated CSV preview and atomic confirmation. Imports use normal posting services."""

import csv
import io
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import ValidationError as SchemaError

from app.core.exceptions import ConflictError, ValidationError
from app.models.inventory import InventoryImport
from app.schemas.inventory import (
    InventoryDocumentCreate,
    InventoryItemCreate,
    InventoryStockPolicyCreate,
)
from app.services.inventory import InventoryService


class InventoryBatchService(InventoryService):
    async def commit(self) -> None:
        await self.session.flush()
        from sqlalchemy import inspect

        for row in list(self.session.identity_map.values()):
            expired = cast(Any, inspect(row)).expired_attributes
            if expired:
                await self.session.refresh(row, attribute_names=list(expired))


class InventoryImports(InventoryService):
    async def apply_row(self, kind: str, row: dict[str, Any]) -> None:
        service = InventoryBatchService(self.session, self.actor)
        if kind == "items":
            await service.master_save("items", InventoryItemCreate.model_validate(row))
        elif kind == "stock-policies":
            await service.master_save(
                "stock-policies", InventoryStockPolicyCreate.model_validate(row)
            )
        elif kind == "opening-stock":
            from app.schemas.inventory import InventoryAction

            body = InventoryDocumentCreate.model_validate(row)
            doc = await service.document_save("receipts", body)
            await service.action("receipts", doc["id"], "post", InventoryAction())
        else:
            raise ValidationError("Supported imports: items, stock-policies, opening-stock")

    async def preview(self, kind: str, data: bytes, filename: str) -> Any:
        await self.lock()
        try:
            reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        except UnicodeDecodeError as error:
            raise ValidationError("CSV must use UTF-8 encoding") from error
        rows = []
        errors = []
        for index, row in enumerate(reader, 2):
            if index > 201:
                raise ValidationError("Import at most 200 rows per file")
            if None in row:
                raise ValidationError("CSV row has too many columns")
            cleaned = {key: value.strip() for key, value in row.items() if value and value.strip()}
            if kind == "opening-stock":
                header = {
                    key: cleaned.pop(key)
                    for key in ["store_id", "supplier_id", "reference_number"]
                    if key in cleaned
                }
                cleaned = {**header, "purpose": "OPENING_BALANCE", "items": [cleaned]}
            rows.append(cleaned)
        if not rows:
            raise ValidationError("CSV contains no data rows")
        # Validate the actual operation under a rollback-only outer savepoint.
        preview = await self.session.begin_nested()
        for index, row in enumerate(rows, 2):
            nested = await self.session.begin_nested()
            try:
                await self.apply_row(kind, row)
                await nested.commit()
            except Exception as error:
                await nested.rollback()
                if isinstance(error, SchemaError):
                    message = "; ".join(e["msg"] for e in error.errors())
                else:
                    message = getattr(error, "message", None) or str(error).split("\n")[0]
                errors.append({"row": index, "message": message[:300]})
        await preview.rollback()
        stage = InventoryImport(
            organization_id=self.org,
            kind=kind,
            filename=filename,
            rows=rows,
            errors=errors,
            created_by_id=self.actor.id,
        )
        self.session.add(stage)
        await self.commit()
        return {
            "id": stage.id,
            "kind": kind,
            "rows": self.public(rows),
            "errors": errors,
            "can_import": not errors,
            "row_count": len(rows),
        }

    async def confirm(self, identifier: Any) -> Any:
        await self.lock()
        stage = await self.ref(InventoryImport, identifier, True)
        if stage.status == "COMPLETED":
            return {"status": "COMPLETED", "row_count": len(stage.rows)}
        if stage.errors:
            raise ConflictError("Correct the file errors and upload a new preview")
        for row in stage.rows:
            await self.apply_row(stage.kind, row)
        stage.status = "COMPLETED"
        stage.completed_at = datetime.now(UTC)
        self.audit("import_completed", stage, {"kind": stage.kind, "rows": len(stage.rows)})
        await InventoryService.commit(self)
        return {"status": stage.status, "row_count": len(stage.rows)}
