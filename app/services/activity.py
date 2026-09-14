"""Resolve operational audit subjects without rewriting stored history."""

import re as _re
import uuid as _uuid

from sqlalchemy import select

from app.models import Asset, AssetAssignment, Employee, EmployeeAssignment, Location, Project


async def present_activity(session, org, results):
    event_values = {log.id: dict(log.new_values or {}) for log, _, _ in results}
    for log, _, _ in results:
        identity_key = {
            "project": "project_id",
            "employee": "employee_id",
            "asset": "asset_id",
            "location": "site_id",
        }.get(log.entity_type)
        if identity_key and log.entity_id:
            event_values[log.id].setdefault(identity_key, str(log.entity_id))
    for model, kinds, fields in [
        (
            EmployeeAssignment,
            {"employee_assignment", "employee_assignments"},
            ["employee_id", "project_id"],
        ),
        (
            AssetAssignment,
            {"asset_assignment", "asset_assignments"},
            ["asset_id", "project_id"],
        ),
        (Location, {"location", "locations"}, ["project_id"]),
    ]:
        identifiers = [log.entity_id for log, _, _ in results if log.entity_type in kinds]
        if not identifiers:
            continue
        parents = {
            row.id: row
            for row in (
                await session.scalars(
                    select(model).where(model.organization_id == org, model.id.in_(identifiers))
                )
            ).all()
        }
        for log, _, _ in results:
            parent = parents.get(log.entity_id) if log.entity_type in kinds else None
            if parent:
                for key in fields:
                    value = getattr(parent, key, None)
                    if value:
                        event_values[log.id].setdefault(key, str(value))

    # ── Collect all UUID references that need name resolution ─────────────
    _UUID_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I)

    def _is_uuid(v: object) -> bool:
        return isinstance(v, str) and bool(_UUID_RE.match(v))

    emp_ids: set[str] = set()
    proj_ids: set[str] = set()
    asset_ids: set[str] = set()
    site_ids: set[str] = set()

    for log, _, __ in results:
        for blob in (event_values[log.id], log.old_values or {}):
            for k, v in (blob or {}).items():
                if not _is_uuid(v):
                    continue
                if any(x in k for x in ("employee", "supervisor", "worker", "manager")):
                    emp_ids.add(v)
                elif "project" in k or k == "transfer_to":
                    proj_ids.add(v)
                elif "asset" in k:
                    asset_ids.add(v)
                elif k in {"site_id", "location_id"}:
                    site_ids.add(v)

    # ── Batch-load names ──────────────────────────────────────────────────
    emp_map: dict[str, str] = {}
    proj_map: dict[str, str] = {}
    asset_map: dict[str, str] = {}

    if emp_ids:
        emp_rows = (
            await session.scalars(
                select(Employee).where(
                    Employee.organization_id == org,
                    Employee.id.in_([_uuid.UUID(i) for i in emp_ids]),
                )
            )
        ).all()
        emp_map = {
            str(e.id): f"{e.first_name or ''} {e.last_name or ''}".strip() or str(e.id)
            for e in emp_rows
        }

    if proj_ids:
        proj_rows = (
            await session.scalars(
                select(Project).where(
                    Project.organization_id == org,
                    Project.id.in_([_uuid.UUID(i) for i in proj_ids]),
                )
            )
        ).all()
        proj_map = {str(p.id): (p.name or str(p.id)) for p in proj_rows}

    if asset_ids:
        asset_rows = (
            await session.scalars(
                select(Asset).where(
                    Asset.organization_id == org,
                    Asset.id.in_([_uuid.UUID(i) for i in asset_ids]),
                )
            )
        ).all()
        asset_map = {str(a.id): (getattr(a, "name", None) or str(a.id)) for a in asset_rows}

    site_map = {}
    if site_ids:
        sites = (
            await session.scalars(
                select(Location).where(
                    Location.organization_id == org,
                    Location.id.in_([_uuid.UUID(i) for i in site_ids]),
                )
            )
        ).all()
        site_map = {str(site.id): site.name for site in sites}

    def _resolve(key: str, val: str) -> str:
        if any(x in key for x in ("employee", "supervisor", "worker", "manager")):
            return emp_map.get(val, val)
        if "project" in key or key == "transfer_to":
            return proj_map.get(val, val)
        if "asset" in key:
            return asset_map.get(val, val)
        if key in {"site_id", "location_id"}:
            return site_map.get(val, val)
        return val

    def _enrich(blob: dict | None) -> dict:
        if not blob:
            return {}
        operational_fields = {
            "name",
            "title",
            "full_name",
            "employee_id",
            "project_id",
            "asset_id",
            "supervisor_id",
            "project_manager_id",
            "site_id",
            "location_id",
            "location_type",
            "description",
            "notes",
            "reason",
            "role_on_project",
            "role",
            "transfer_to",
            "status",
            "assignment_number",
            "employee_number",
            "asset_number",
            "project_number",
            "document_number",
            "transaction_number",
            "reference_number",
            "record_type",
            "report_type",
            "report_id",
            "site_name",
            "report_date",
            "metres",
            "drill_holes",
            "average_depth",
            "file_name",
            "size_bytes",
            "quantity",
            "litres",
            "quantity_litres",
            "severity",
            "start_date",
            "end_date",
        }
        return {
            k: (_resolve(k, v) if _is_uuid(v) else v)
            for k, v in blob.items()
            if k in operational_fields
        }

    def _summary(action: str, d: dict) -> str:
        d = {k: v for k, v in d.items() if not _is_uuid(v)}
        emp = d.get("employee_id") or ""
        proj = d.get("project_id") or ""
        sup = d.get("supervisor_id") or ""
        asset = d.get("asset_id") or ""
        role = d.get("role_on_project") or d.get("role") or ""
        transfer_to = proj_map.get(str(d.get("transfer_to") or ""), str(d.get("transfer_to") or ""))

        if action == "employee.assigned":
            parts = [emp or "An employee"]
            if proj:
                parts.append(f"added to {proj}")
            if role:
                parts.append(f"as {role}")
            if sup:
                parts.append(f"(supervisor: {sup})")
            return " ".join(parts)

        if action == "employee.assignment_updated":
            parts = [emp] if emp else []
            if proj:
                parts.append(f"assignment on {proj} updated")
            if sup:
                parts.append(f"— supervisor set to {sup}")
            if role:
                parts.append(f"— role: {role}")
            return " ".join(parts) or "Assignment updated"

        if action in {
            "employee.assignment_cancelled",
            "asset.assignment_completed",
            "asset.assignment_updated",
        }:
            return f"{emp or asset or 'Assignment'}: {action.split('.')[-1].replace('_', ' ')}"

        if action == "employee.assignment_completed":
            parts = [emp or "Employee", "assignment completed"]
            if proj:
                parts.append(f"on {proj}")
            if transfer_to:
                parts.append(f"(transferred to {transfer_to})")
            return " ".join(parts)

        if action == "employee.transferred":
            parts = [emp or "Employee", "transferred"]
            if proj:
                parts.append(f"to {proj}")
            return " ".join(parts)

        if action == "employee.created":
            return f"{emp or 'New employee'} onboarded"

        if action == "employee.updated":
            return f"{emp or 'Employee'} profile updated"

        if action == "employee.archived":
            return f"{emp or 'Employee'} archived"

        if action in {"asset.assigned", "asset.transferred"}:
            parts = [asset or "Asset"]
            if proj:
                verb = "transferred" if action == "asset.transferred" else "assigned"
                parts.append(f"{verb} to {proj}")
            return " ".join(parts)

        if action == "asset.unassigned":
            return f"{asset or 'Asset'} removed from assignment"

        if action == "asset.maintenance_created":
            title = d.get("title") or "Maintenance"
            return f"{title} logged{f' for {asset}' if asset else ''}"

        if action == "asset.fuel_logged":
            qty = d.get("quantity") or d.get("litres") or ""
            return f"Fuel logged{f' ({qty}L)' if qty else ''}{f' for {asset}' if asset else ''}"

        if action == "asset.defect_reported":
            return f"Defect reported{f' on {asset}' if asset else ''}"

        if action == "project.created":
            return f"Project {proj or ''} created".strip()

        if action == "project.updated":
            return f"Project {proj or ''} details updated".strip()

        if action == "project.report_created":
            title = d.get("title") or "Report"
            site = d.get("site_name") or ""
            return f"{title} submitted{f' at {site}' if site else ''}"

        if action == "project.report_updated":
            return f"{d.get('title') or 'Report'} updated"

        if action.startswith("project.record_"):
            kind = str(d.get("record_type") or "record").lower()
            return f"{kind.capitalize()} {d.get('title') or ''} {action.rsplit('_', 1)[-1]}".strip()

        if action in {"location.created", "location.updated"}:
            site = d.get("name") or d.get("site_id") or "Site"
            verb = "added" if action.endswith("created") else "updated"
            return f"{site} {verb}{f' on {proj}' if proj else ''}"

        if action == "inventory.created":
            return f"Inventory item '{d.get('name') or 'new'}' added"

        if action == "inventory.updated":
            return f"Inventory item '{d.get('name') or ''}' updated"

        if action == "transfer.created":
            return "Stock transfer dispatched"

        # Generic fallback
        for key in ("name", "title", "full_name"):
            if d.get(key):
                return str(d[key])
        return (action or "activity").replace(".", " ").replace("_", " ").capitalize()

    items = []
    for log, fname, lname in results:
        author_name = f"{fname or ''} {lname or ''}".strip() or "System"
        enriched_details = _enrich(event_values[log.id])
        enriched_previous = _enrich(log.old_values)
        summary = _summary(log.action or "", enriched_details)
        event_title = (log.action or "activity").replace(".", " ").replace("_", " ").title()
        if log.action.startswith("project.record_"):
            kind = str(enriched_details.get("record_type") or "Record").title()
            event_title = f"{kind} {log.action.rsplit('_', 1)[-1].title()}"
        elif log.action.startswith("location."):
            event_title = "Site " + log.action.split(".")[-1].replace("_", " ").title()
        items.append(
            {
                "id": str(log.id),
                "action": log.action,
                "title": event_title,
                "summary": summary,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "actor_user_id": str(log.actor_user_id) if log.actor_user_id else None,
                "author_name": author_name,
                "details": enriched_details,
                "previous": enriched_previous,
            }
        )
    return items
