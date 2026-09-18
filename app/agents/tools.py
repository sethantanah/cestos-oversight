"""Agentic tool definitions and execution functions for the Cestos Smart Assistant.

Provides OpenAI-compatible function/tool definitions and safe, org-scoped
execution functions that build SQLAlchemy queries dynamically.
"""

import uuid
from decimal import Decimal
from datetime import date, datetime
from typing import Any
from pathlib import Path

from sqlalchemy import func, select, or_, and_, inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import (
    Employee, EmployeeAssignment, Department, Position,
    Skill, EmployeeSkill, EmployeeQualification,
    AssignmentStatus, EmploymentStatus, EmployeeDocument,
    EmployeeLicense, EmployeeRotation, LeaveRequest, TimeLog,
)
from app.models.asset import Asset, AssetCategory, AssetStatus
from app.models.project import Project, ProjectStatus
from app.models.location import Location
from app.models.inventory import (
    InventoryItem, InventoryStore, InventoryBalance, InventoryCategory,
)
from app.models.operational_logs import AssetFuelLog, AssetMaintenanceJob
from app.models.asset_records import AssetDefect
from app.models.hr import Salary as EmployeeSalary
from app.models.document_library import LibraryDocument
from app.services.document_index import search_vectors


# ---------------------------------------------------------------------------
# Skills document (loaded once, cached)
# ---------------------------------------------------------------------------
_SKILLS_CACHE: str | None = None


def load_skills_prompt() -> str:
    """Load skills.md as the LLM system prompt component."""
    global _SKILLS_CACHE
    if _SKILLS_CACHE is None:
        skills_path = Path(__file__).parent / "skills.md"
        _SKILLS_CACHE = skills_path.read_text(encoding="utf-8")
    return _SKILLS_CACHE


# ---------------------------------------------------------------------------
# Model registry — maps table name strings to SQLAlchemy model classes
# ---------------------------------------------------------------------------
TABLE_REGISTRY: dict[str, Any] = {
    "employees": Employee,
    "departments": Department,
    "positions": Position,
    "projects": Project,
    "assets": Asset,
    "asset_categories": AssetCategory,
    "locations": Location,
    "inventory_items": InventoryItem,
    "inventory_stores": InventoryStore,
    "inventory_balances": InventoryBalance,
    "inventory_categories": InventoryCategory,
    "employee_assignments": EmployeeAssignment,
    "employee_skills": EmployeeSkill,
    "skills": Skill,
    "employee_qualifications": EmployeeQualification,
    "employee_documents": EmployeeDocument,
    "employee_licenses": EmployeeLicense,
    "employee_salaries": EmployeeSalary,
    "asset_fuel_logs": AssetFuelLog,
    "asset_maintenance_jobs": AssetMaintenanceJob,
    "asset_defects": AssetDefect,
    "leave_requests": LeaveRequest,
    "time_logs": TimeLog,
    "employee_rotations": EmployeeRotation,
    "library_documents": LibraryDocument,
}


# ---------------------------------------------------------------------------
# OpenAI Tool Definitions (function calling schema)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "Execute a dynamic read-only database query. Supports counting, listing, filtering, and aggregating data from any table. All queries are automatically scoped to the current user's organization.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": list(TABLE_REGISTRY.keys()),
                        "description": "The database table to query.",
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["count", "list", "aggregate", "distinct"],
                        "description": "The type of query operation.",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {
                                    "type": "string",
                                    "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "in", "is_null", "not_null"],
                                },
                                "value": {"type": "string"},
                            },
                            "required": ["column", "op"],
                        },
                        "description": "Optional filters to apply.",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Columns to return for 'list' or 'distinct' operations.",
                    },
                    "aggregate_column": {
                        "type": "string",
                        "description": "Column to aggregate (for 'aggregate' operation).",
                    },
                    "aggregate_function": {
                        "type": "string",
                        "enum": ["sum", "avg", "min", "max", "count_distinct"],
                        "description": "Aggregate function to apply.",
                    },
                    "group_by": {
                        "type": "string",
                        "description": "Column to group results by.",
                    },
                    "order_by": {
                        "type": "string",
                        "description": "Column to sort results by.",
                    },
                    "order_dir": {
                        "type": "string",
                        "enum": ["asc", "desc"],
                        "description": "Sort direction.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum rows to return (default 20, max 50).",
                    },
                },
                "required": ["table", "operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Semantic search across uploaded organization documents (PDFs, CVs, policies, contracts, manuals) using FAISS vector embeddings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (1-10, default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_schema",
            "description": "Inspect a database table's column definitions, types, and relationships. Use this when unsure of exact column names.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Table or model name to inspect.",
                    },
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_details",
            "description": "Look up employees with optional joins to project assignments, skills, and qualifications. Best for questions about specific people, department members, or personnel with certain skills.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_name": {
                        "type": "string",
                        "description": "Partial name match (searches first_name, last_name).",
                    },
                    "employee_id": {
                        "type": "string",
                        "description": "Exact employee UUID.",
                    },
                    "department": {
                        "type": "string",
                        "description": "Department name filter (partial match).",
                    },
                    "department_id": {
                        "type": "string",
                        "description": "Exact department UUID.",
                    },
                    "employment_status": {
                        "type": "string",
                        "enum": [s.value for s in EmploymentStatus],
                        "description": "Employment status filter.",
                    },
                    "job_title": {
                        "type": "string",
                        "description": "Job title search (partial match).",
                    },
                    "include_assignments": {
                        "type": "boolean",
                        "description": "Include project assignments. Default true.",
                    },
                    "include_skills": {
                        "type": "boolean",
                        "description": "Include skills and qualifications. Default false.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 10.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_details",
            "description": "Look up projects with optional assigned personnel and locations. Best for questions about specific projects, active project listings, or who works on which project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_name": {
                        "type": "string",
                        "description": "Project name search (partial match).",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Exact project UUID.",
                    },
                    "status": {
                        "type": "string",
                        "enum": [s.value for s in ProjectStatus],
                        "description": "Project status filter.",
                    },
                    "include_assignments": {
                        "type": "boolean",
                        "description": "Include assigned employees. Default true.",
                    },
                    "include_locations": {
                        "type": "boolean",
                        "description": "Include project locations. Default false.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 10.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fleet_summary",
            "description": "Get fleet/asset analytics with status breakdown, optional fuel consumption, and maintenance data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "enum": [s.value for s in AssetStatus],
                        "description": "Filter assets by status.",
                    },
                    "category_filter": {
                        "type": "string",
                        "description": "Asset category name filter (partial match).",
                    },
                    "include_fuel": {
                        "type": "boolean",
                        "description": "Include fuel consumption totals. Default false.",
                    },
                    "include_maintenance": {
                        "type": "boolean",
                        "description": "Include maintenance job counts and costs. Default false.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max asset listing results. Default 10.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_summary",
            "description": "Get inventory stock levels, valuations, and category breakdowns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Inventory category filter.",
                    },
                    "store_name": {
                        "type": "string",
                        "description": "Store name filter (partial match).",
                    },
                    "low_stock_only": {
                        "type": "boolean",
                        "description": "Only show items at or below reorder point. Default false.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 10.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_summary",
            "description": "Get financial overview including payroll totals and fuel expenditure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_payroll": {
                        "type": "boolean",
                        "description": "Include salary/payroll data. Default true.",
                    },
                    "include_fuel_costs": {
                        "type": "boolean",
                        "description": "Include fuel expenditure data. Default true.",
                    },
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------

def _serialize(value: Any) -> Any:
    """Convert non-JSON-serializable types to strings."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum := type(value)) and hasattr(value, "value"):
        return value.value if hasattr(value, "value") else str(value)
    return value


def _row_to_dict(row, columns: list[str]) -> dict[str, Any]:
    """Convert a SQLAlchemy row tuple to a serializable dict."""
    result = {}
    for i, col in enumerate(columns):
        val = row[i] if i < len(row) else None
        result[col] = _serialize(val)
    return result


# ---------------------------------------------------------------------------
# Tool Execution Functions
# ---------------------------------------------------------------------------

def _get_column(model, col_name: str):
    """Get a column attribute from a model, returns None if not found."""
    if hasattr(model, col_name):
        return getattr(model, col_name)
    return None


def _apply_filter(model, col_attr, f: dict) -> Any:
    """Build a SQLAlchemy filter clause from a filter dict."""
    op = f.get("op", "eq")
    val = f.get("value", "")

    if op == "eq":
        return col_attr == val
    elif op == "neq":
        return col_attr != val
    elif op == "gt":
        return col_attr > val
    elif op == "gte":
        return col_attr >= val
    elif op == "lt":
        return col_attr < val
    elif op == "lte":
        return col_attr <= val
    elif op == "like":
        return col_attr.like(val)
    elif op == "ilike":
        return col_attr.ilike(val)
    elif op == "in":
        values = [v.strip() for v in val.split(",")]
        return col_attr.in_(values)
    elif op == "is_null":
        return col_attr.is_(None)
    elif op == "not_null":
        return col_attr.isnot(None)
    return col_attr == val


async def execute_query_database(args: dict[str, Any], org_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
    """Execute a dynamic database query with org scoping."""
    table_name = args.get("table", "")
    operation = args.get("operation", "list")
    filters = args.get("filters", [])
    columns = args.get("columns", [])
    limit = min(args.get("limit", 20), 50)

    model = TABLE_REGISTRY.get(table_name)
    if not model:
        return {"error": f"Unknown table: {table_name}", "available_tables": list(TABLE_REGISTRY.keys())}

    try:
        # Build base conditions (org scoping + soft delete)
        conditions = []
        if hasattr(model, "organization_id"):
            conditions.append(model.organization_id == org_id)
        if hasattr(model, "archived_at"):
            conditions.append(model.archived_at.is_(None))

        # Apply user filters
        for f in filters:
            col_attr = _get_column(model, f["column"])
            if col_attr is None:
                available = [c.name for c in model.__table__.columns]
                return {"error": f"Column '{f['column']}' not found on {table_name}", "available_columns": available}
            conditions.append(_apply_filter(model, col_attr, f))

        if operation == "count":
            stmt = select(func.count(model.id)).where(*conditions)
            result = (await session.execute(stmt)).scalar() or 0
            return {"count": result, "table": table_name}

        elif operation == "aggregate":
            agg_col_name = args.get("aggregate_column", "")
            agg_func = args.get("aggregate_function", "sum")
            group_by_col = args.get("group_by")

            agg_col = _get_column(model, agg_col_name)
            if agg_col is None:
                return {"error": f"Aggregate column '{agg_col_name}' not found on {table_name}"}

            agg_map = {
                "sum": func.sum,
                "avg": func.avg,
                "min": func.min,
                "max": func.max,
                "count_distinct": lambda c: func.count(func.distinct(c)),
            }
            agg_fn = agg_map.get(agg_func, func.sum)

            if group_by_col:
                gb_attr = _get_column(model, group_by_col)
                if gb_attr is None:
                    return {"error": f"Group-by column '{group_by_col}' not found"}
                stmt = select(gb_attr, agg_fn(agg_col).label("value")).where(*conditions).group_by(gb_attr)
                rows = (await session.execute(stmt)).all()
                return {
                    "results": [{"group": _serialize(r[0]), "value": _serialize(r[1])} for r in rows],
                    "aggregate_function": agg_func,
                    "column": agg_col_name,
                }
            else:
                stmt = select(agg_fn(agg_col).label("value")).where(*conditions)
                result = (await session.execute(stmt)).scalar()
                return {"value": _serialize(result), "aggregate_function": agg_func, "column": agg_col_name}

        elif operation == "distinct":
            if not columns:
                return {"error": "Must specify 'columns' for distinct operation"}
            col_attrs = []
            for c in columns:
                attr = _get_column(model, c)
                if attr is None:
                    return {"error": f"Column '{c}' not found on {table_name}"}
                col_attrs.append(attr)
            stmt = select(*col_attrs).distinct().where(*conditions).limit(limit)
            rows = (await session.execute(stmt)).all()
            return {"distinct_values": [_row_to_dict(r, columns) for r in rows], "table": table_name}

        else:  # list
            if not columns:
                # Default: pick useful columns
                all_cols = [c.name for c in model.__table__.columns if c.name not in ("organization_id", "archived_at", "created_by_id", "updated_by_id", "updated_at", "created_at")]
                columns = all_cols[:8]

            col_attrs = []
            for c in columns:
                attr = _get_column(model, c)
                if attr is None:
                    return {"error": f"Column '{c}' not found on {table_name}", "available_columns": [col.name for col in model.__table__.columns]}
                col_attrs.append(attr)

            stmt = select(*col_attrs).where(*conditions)

            # Order by
            order_col = args.get("order_by")
            if order_col:
                order_attr = _get_column(model, order_col)
                if order_attr is not None:
                    if args.get("order_dir", "asc") == "desc":
                        stmt = stmt.order_by(order_attr.desc())
                    else:
                        stmt = stmt.order_by(order_attr)

            stmt = stmt.limit(limit)
            rows = (await session.execute(stmt)).all()
            return {"rows": [_row_to_dict(r, columns) for r in rows], "count": len(rows), "table": table_name}

    except Exception as e:
        # On error, return schema info for self-correction
        try:
            available = [c.name for c in model.__table__.columns]
        except Exception:
            available = []
        return {"error": str(e), "table": table_name, "available_columns": available}


async def execute_search_documents(args: dict[str, Any], org_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
    """Execute semantic document search via FAISS vectors."""
    query = args.get("query", "")
    max_results = min(args.get("max_results", 5), 10)

    docs_res = await session.execute(
        select(LibraryDocument).where(
            LibraryDocument.organization_id == org_id,
            LibraryDocument.is_active.is_(True),
        )
    )
    docs = docs_res.scalars().all()
    if not docs:
        return {"results": [], "message": "No documents found in the organization's library."}

    ready_docs = [d for d in docs if d.index_status == "READY"]
    if not ready_docs:
        return {"results": [], "message": "No indexed documents available for search."}

    hits = search_vectors(ready_docs, query)
    citations = []

    for doc in ready_docs:
        if doc.id in hits:
            score, chunk = hits[doc.id]
            if score >= 0.45:
                citations.append({
                    "document_id": str(doc.id),
                    "employee_id": str(doc.employee_id) if doc.employee_id else None,
                    "title": doc.title or doc.file_name,
                    "file_name": doc.file_name,
                    "category": doc.category or "General",
                    "snippet": chunk.get("text", "")[:400],
                    "relevance_score": round(score, 3),
                })

    citations.sort(key=lambda x: x["relevance_score"], reverse=True)
    return {"results": citations[:max_results], "total_indexed_documents": len(ready_docs)}


def execute_inspect_schema(args: dict[str, Any]) -> dict[str, Any]:
    """Inspect a table's column definitions."""
    table_name = args.get("table_name", "").lower().rstrip("s")

    # Try exact match first, then singular/plural variants
    model = TABLE_REGISTRY.get(table_name) or TABLE_REGISTRY.get(table_name + "s")
    if not model:
        # Try partial match
        for key, m in TABLE_REGISTRY.items():
            if table_name in key or key in table_name:
                model = m
                break

    if not model:
        return {"error": f"Table '{table_name}' not found", "available_tables": list(TABLE_REGISTRY.keys())}

    columns = {}
    for col in model.__table__.columns:
        col_info = {"type": str(col.type)}
        if col.foreign_keys:
            col_info["foreign_key"] = str(list(col.foreign_keys)[0].target_fullname)
        if col.nullable is False:
            col_info["required"] = True
        columns[col.name] = col_info

    return {
        "model_name": model.__name__,
        "table_name": model.__tablename__,
        "columns": columns,
    }


async def execute_get_employee_details(args: dict[str, Any], org_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
    """Look up employees with optional assignments, skills, and qualifications."""
    limit = min(args.get("limit", 10), 30)
    include_assignments = args.get("include_assignments", True)
    include_skills = args.get("include_skills", False)

    conditions = [Employee.organization_id == org_id, Employee.archived_at.is_(None)]

    search_name = args.get("search_name")
    if search_name:
        name_parts = search_name.strip().split()
        name_conditions = []
        for part in name_parts:
            name_conditions.append(Employee.first_name.ilike(f"%{part}%"))
            name_conditions.append(Employee.last_name.ilike(f"%{part}%"))
        conditions.append(or_(*name_conditions))

    emp_id = args.get("employee_id")
    if emp_id:
        try:
            conditions.append(Employee.id == uuid.UUID(emp_id))
        except ValueError:
            return {"error": f"Invalid employee_id format: {emp_id}"}

    dept = args.get("department")
    if dept:
        conditions.append(Employee.department.ilike(f"%{dept}%"))

    dept_id = args.get("department_id")
    if dept_id:
        try:
            conditions.append(Employee.department_id == uuid.UUID(dept_id))
        except ValueError:
            pass

    status = args.get("employment_status")
    if status:
        conditions.append(Employee.employment_status == status)

    title = args.get("job_title")
    if title:
        conditions.append(Employee.job_title.ilike(f"%{title}%"))

    stmt = select(
        Employee.id, Employee.employee_number, Employee.first_name, Employee.last_name,
        Employee.department, Employee.job_title, Employee.employment_status,
        Employee.work_email, Employee.primary_phone, Employee.hire_date,
    ).where(*conditions).limit(limit)

    rows = (await session.execute(stmt)).all()
    employees = []

    for row in rows:
        emp = {
            "id": str(row[0]),
            "employee_number": row[1],
            "name": f"{row[2]} {row[3]}",
            "first_name": row[2],
            "last_name": row[3],
            "department": row[4] or "Unassigned",
            "job_title": row[5] or "Staff",
            "employment_status": _serialize(row[6]),
            "work_email": row[7],
            "phone": row[8],
            "hire_date": _serialize(row[9]),
        }

        if include_assignments:
            assgn_stmt = (
                select(
                    EmployeeAssignment.id,
                    EmployeeAssignment.role_on_project,
                    EmployeeAssignment.status,
                    EmployeeAssignment.start_date,
                    EmployeeAssignment.end_date,
                    Project.id.label("project_id"),
                    Project.name.label("project_name"),
                    Project.status.label("project_status"),
                    Location.name.label("location_name"),
                )
                .join(Project, EmployeeAssignment.project_id == Project.id)
                .outerjoin(Location, EmployeeAssignment.location_id == Location.id)
                .where(
                    EmployeeAssignment.employee_id == row[0],
                    EmployeeAssignment.organization_id == org_id,
                )
                .order_by(EmployeeAssignment.status.asc())
            )
            assignments = (await session.execute(assgn_stmt)).all()
            emp["assignments"] = [
                {
                    "assignment_id": str(a[0]),
                    "role": a[1] or emp["job_title"],
                    "status": _serialize(a[2]),
                    "start_date": _serialize(a[3]),
                    "end_date": _serialize(a[4]),
                    "project_id": str(a[5]),
                    "project_name": a[6],
                    "project_status": _serialize(a[7]),
                    "location": a[8] or "N/A",
                }
                for a in assignments
            ]

        if include_skills:
            sk_stmt = (
                select(Skill.name, EmployeeSkill.proficiency_level)
                .join(Skill, EmployeeSkill.skill_id == Skill.id)
                .where(EmployeeSkill.employee_id == row[0])
            )
            skills = (await session.execute(sk_stmt)).all()
            emp["skills"] = [{"name": s[0], "level": _serialize(s[1])} for s in skills]

            q_stmt = (
                select(EmployeeQualification.qualification_name, EmployeeQualification.field_of_study, EmployeeQualification.institution)
                .where(EmployeeQualification.employee_id == row[0])
            )
            quals = (await session.execute(q_stmt)).all()
            emp["qualifications"] = [{"name": q[0], "field": q[1], "institution": q[2]} for q in quals]

        employees.append(emp)

    return {"employees": employees, "count": len(employees)}


async def execute_get_project_details(args: dict[str, Any], org_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
    """Look up projects with optional personnel and locations."""
    limit = min(args.get("limit", 10), 30)
    include_assignments = args.get("include_assignments", True)
    include_locations = args.get("include_locations", False)

    conditions = [Project.organization_id == org_id, Project.archived_at.is_(None)]

    search_name = args.get("search_name")
    if search_name:
        conditions.append(Project.name.ilike(f"%{search_name}%"))

    proj_id = args.get("project_id")
    if proj_id:
        try:
            conditions.append(Project.id == uuid.UUID(proj_id))
        except ValueError:
            return {"error": f"Invalid project_id: {proj_id}"}

    status = args.get("status")
    if status:
        conditions.append(Project.status == status)

    stmt = select(
        Project.id, Project.project_number, Project.name, Project.status,
        Project.target_metres, Project.contract_value, Project.start_date,
        Project.expected_end_date, Project.description,
    ).where(*conditions).limit(limit)

    rows = (await session.execute(stmt)).all()
    projects = []

    for row in rows:
        proj = {
            "id": str(row[0]),
            "project_number": row[1],
            "name": row[2],
            "status": _serialize(row[3]),
            "target_metres": _serialize(row[4]),
            "contract_value": _serialize(row[5]),
            "start_date": _serialize(row[6]),
            "expected_end_date": _serialize(row[7]),
            "description": (row[8] or "")[:200],
        }

        if include_assignments:
            assgn_stmt = (
                select(
                    Employee.id, Employee.first_name, Employee.last_name,
                    Employee.job_title, EmployeeAssignment.role_on_project,
                    EmployeeAssignment.status,
                )
                .join(Employee, EmployeeAssignment.employee_id == Employee.id)
                .where(
                    EmployeeAssignment.project_id == row[0],
                    EmployeeAssignment.organization_id == org_id,
                )
            )
            personnel = (await session.execute(assgn_stmt)).all()
            proj["assigned_personnel"] = [
                {
                    "employee_id": str(p[0]),
                    "name": f"{p[1]} {p[2]}",
                    "job_title": p[3] or "Staff",
                    "role_on_project": p[4] or p[3] or "Staff",
                    "assignment_status": _serialize(p[5]),
                }
                for p in personnel
            ]

        if include_locations:
            loc_stmt = (
                select(Location.id, Location.name, Location.location_type, Location.city)
                .where(Location.project_id == row[0], Location.organization_id == org_id)
            )
            locs = (await session.execute(loc_stmt)).all()
            proj["locations"] = [
                {"id": str(l[0]), "name": l[1], "type": _serialize(l[2]), "city": l[3]}
                for l in locs
            ]

        projects.append(proj)

    return {"projects": projects, "count": len(projects)}


async def execute_get_fleet_summary(args: dict[str, Any], org_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
    """Get fleet analytics with optional fuel and maintenance data."""
    limit = min(args.get("limit", 10), 30)
    include_fuel = args.get("include_fuel", False)
    include_maintenance = args.get("include_maintenance", False)

    # Status breakdown
    status_stmt = (
        select(Asset.status, func.count(Asset.id))
        .where(Asset.organization_id == org_id, Asset.archived_at.is_(None))
        .group_by(Asset.status)
    )
    status_rows = (await session.execute(status_stmt)).all()
    status_breakdown = {_serialize(s): c for s, c in status_rows}
    total = sum(status_breakdown.values())
    operating = status_breakdown.get("OPERATING", 0) + status_breakdown.get("AVAILABLE", 0)

    result: dict[str, Any] = {
        "total_assets": total,
        "status_breakdown": status_breakdown,
        "operating_fleet": operating,
        "utilization_rate_pct": round(operating / total * 100, 1) if total > 0 else 0,
    }

    # Asset listing (optionally filtered)
    conditions = [Asset.organization_id == org_id, Asset.archived_at.is_(None)]
    status_filter = args.get("status_filter")
    if status_filter:
        conditions.append(Asset.status == status_filter)

    category_filter = args.get("category_filter")
    if category_filter:
        cat_subq = select(AssetCategory.id).where(AssetCategory.name.ilike(f"%{category_filter}%"))
        conditions.append(Asset.category_id.in_(cat_subq))

    asset_stmt = (
        select(Asset.id, Asset.asset_number, Asset.name, Asset.status, Asset.manufacturer, Asset.model)
        .where(*conditions)
        .limit(limit)
    )
    assets = (await session.execute(asset_stmt)).all()
    result["assets"] = [
        {
            "id": str(a[0]), "asset_number": a[1], "name": a[2],
            "status": _serialize(a[3]), "manufacturer": a[4], "model": a[5],
        }
        for a in assets
    ]

    if include_fuel:
        fuel_stmt = (
            select(
                func.sum(AssetFuelLog.quantity_litres).label("total_litres"),
                func.sum(AssetFuelLog.quantity_litres * AssetFuelLog.unit_cost).label("total_cost"),
                func.count(AssetFuelLog.id).label("log_count"),
            )
            .where(AssetFuelLog.organization_id == org_id)
        )
        fuel = (await session.execute(fuel_stmt)).one()
        result["fuel_summary"] = {
            "total_litres": _serialize(fuel[0] or 0),
            "total_cost": _serialize(fuel[1] or 0),
            "log_count": fuel[2] or 0,
        }

    if include_maintenance:
        maint_stmt = (
            select(
                AssetMaintenanceJob.status,
                func.count(AssetMaintenanceJob.id),
                func.sum(AssetMaintenanceJob.cost),
            )
            .where(AssetMaintenanceJob.organization_id == org_id)
            .group_by(AssetMaintenanceJob.status)
        )
        maint_rows = (await session.execute(maint_stmt)).all()
        result["maintenance_summary"] = [
            {"status": s, "count": c, "total_cost": _serialize(cost or 0)}
            for s, c, cost in maint_rows
        ]

    return result


async def execute_get_inventory_summary(args: dict[str, Any], org_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
    """Get inventory stock levels and valuations."""
    limit = min(args.get("limit", 10), 30)

    # Overall totals
    totals_stmt = (
        select(
            func.count(func.distinct(InventoryItem.id)),
            func.coalesce(func.sum(InventoryBalance.inventory_value), 0),
            func.coalesce(func.sum(InventoryBalance.quantity_on_hand), 0),
        )
        .select_from(InventoryItem)
        .outerjoin(InventoryBalance, InventoryItem.id == InventoryBalance.item_id)
        .where(InventoryItem.organization_id == org_id, InventoryItem.archived_at.is_(None))
    )
    totals = (await session.execute(totals_stmt)).one()

    # Stores count and breakdown
    store_stmt = (
        select(func.count(InventoryStore.id))
        .where(InventoryStore.organization_id == org_id, InventoryStore.archived_at.is_(None))
    )
    store_count = (await session.execute(store_stmt)).scalar() or 0

    result: dict[str, Any] = {
        "total_items": totals[0] or 0,
        "total_stores": store_count,
        "total_value": _serialize(totals[1]),
        "total_quantity_on_hand": _serialize(totals[2]),
    }

    # Item listing
    conditions = [InventoryItem.organization_id == org_id, InventoryItem.archived_at.is_(None)]

    category = args.get("category")
    if category:
        cat_subq = select(InventoryCategory.id).where(InventoryCategory.name.ilike(f"%{category}%"))
        conditions.append(InventoryItem.category_id.in_(cat_subq))

    item_stmt = (
        select(
            InventoryItem.id, InventoryItem.name, InventoryItem.item_number,
            InventoryItem.sku,
            func.coalesce(func.sum(InventoryBalance.quantity_on_hand), 0).label("qty"),
            func.coalesce(func.sum(InventoryBalance.inventory_value), 0).label("val"),
        )
        .outerjoin(InventoryBalance, InventoryItem.id == InventoryBalance.item_id)
        .where(*conditions)
        .group_by(InventoryItem.id, InventoryItem.name, InventoryItem.item_number, InventoryItem.sku)
        .limit(limit)
    )
    items = (await session.execute(item_stmt)).all()
    result["items"] = [
        {
            "id": str(i[0]), "name": i[1], "item_number": i[2],
            "sku": i[3], "quantity_on_hand": _serialize(i[4]),
            "value": _serialize(i[5]),
        }
        for i in items
    ]

    return result


async def execute_get_financial_summary(args: dict[str, Any], org_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
    """Get financial overview: payroll and fuel costs."""
    result: dict[str, Any] = {}

    if args.get("include_payroll", True):
        sal_stmt = (
            select(
                func.count(EmployeeSalary.id),
                func.sum(EmployeeSalary.amount),
                func.avg(EmployeeSalary.amount),
            )
            .where(EmployeeSalary.organization_id == org_id)
        )
        sal = (await session.execute(sal_stmt)).one()
        result["payroll"] = {
            "active_records": sal[0] or 0,
            "total_base_payroll": _serialize(sal[1] or 0),
            "average_salary": _serialize(sal[2] or 0),
        }

    if args.get("include_fuel_costs", True):
        fuel_stmt = (
            select(
                func.sum(AssetFuelLog.quantity_litres * AssetFuelLog.unit_cost).label("total_cost"),
                func.sum(AssetFuelLog.quantity_litres).label("total_litres"),
                func.count(AssetFuelLog.id),
            )
            .where(AssetFuelLog.organization_id == org_id)
        )
        fuel = (await session.execute(fuel_stmt)).one()
        result["fuel_costs"] = {
            "total_fuel_expenditure": _serialize(fuel[0] or 0),
            "total_litres_consumed": _serialize(fuel[1] or 0),
            "total_fuel_logs": fuel[2] or 0,
        }

    return result



# ---------------------------------------------------------------------------
# Tool Dispatcher
# ---------------------------------------------------------------------------

TOOL_EXECUTORS = {
    "query_database": "db",
    "search_documents": "db",
    "inspect_schema": "sync",
    "get_employee_details": "db",
    "get_project_details": "db",
    "get_fleet_summary": "db",
    "get_inventory_summary": "db",
    "get_financial_summary": "db",
}


async def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    org_id: uuid.UUID,
    session: AsyncSession,
) -> dict[str, Any]:
    """Dispatch and execute a tool call by name."""
    try:
        if tool_name == "query_database":
            return await execute_query_database(args, org_id, session)
        elif tool_name == "search_documents":
            return await execute_search_documents(args, org_id, session)
        elif tool_name == "inspect_schema":
            return execute_inspect_schema(args)
        elif tool_name == "get_employee_details":
            return await execute_get_employee_details(args, org_id, session)
        elif tool_name == "get_project_details":
            return await execute_get_project_details(args, org_id, session)
        elif tool_name == "get_fleet_summary":
            return await execute_get_fleet_summary(args, org_id, session)
        elif tool_name == "get_inventory_summary":
            return await execute_get_inventory_summary(args, org_id, session)
        elif tool_name == "get_financial_summary":
            return await execute_get_financial_summary(args, org_id, session)
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}", "tool": tool_name}
