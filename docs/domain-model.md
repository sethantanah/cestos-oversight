# Cestos Operational Core — Domain Model

First operational layer: people, projects, assets, locations and assignments.
Maintenance, fuel, inventory, drilling production, procurement, finance and
dashboards build on these tables later and are intentionally not implemented.

## Relationship diagram

```text
CLIENT
  |
  +----< PROJECT
           |
           +----< LOCATION (project_id nullable; head office/workshop/yard
           |               have no project)
           |
           +----< EMPLOYEE_ASSIGNMENT >---- EMPLOYEE
           |         (status PLANNED/      (supervisor_id self-FK,
           |          ACTIVE/COMPLETED/     skills, documents)
           |          CANCELLED)
           |
           +----< ASSET_ASSIGNMENT >------- ASSET
                        (at most one        (category, default location,
                         ACTIVE per          responsible employee)
                         asset)                 |
                                                +----< ASSET_COMPONENT
                                                |
                                                +----< METER_READING
```

`SKILL` links to `EMPLOYEE` through `EMPLOYEE_SKILL`
(unique per organization/employee/skill).
`BUSINESS_COUNTER` backs readable identifiers and is not a domain entity.

## Assignment philosophy

- Assignments are history. Completing an assignment sets `end_date`/`status`
  (employee) or `returned_at`/`status` (asset). Rows are never deleted.
- Current project/location is derived from `ACTIVE` assignment rows, never from
  a `current_project_id` column. No denormalized copies exist yet.
- One primary `ACTIVE` employee assignment per employee and at most one
  `ACTIVE` assignment per asset are enforced at the service layer (409 Conflict).
- Invalid dates (`end_date < start_date`, `returned_at < assigned_at`) are
  rejected (422). Cross-organization links are rejected (404 on the foreign id).
- Meter readings cannot decrease per asset/meter-type unless resubmitted with
  `is_correction: true` and a reason in `notes` (meter replacement/reset).

## Business identifiers

UUIDs are primary keys. Human-readable numbers come from the
`business_counters(organization_id, entity_type, current_value)` table,
incremented with `SELECT ... FOR UPDATE` inside the creating transaction —
no `MAX()+1` race conditions:

| Entity | Prefix | Counter key |
| --- | --- | --- |
| Employee | `EMP-000001` | `employee` |
| Client | `CLI-000001` | `client` |
| Project | `PRJ-000001` | `project` |
| Location | `SITE-000001` | `location` |
| Asset | `AST-000001` | `asset` |
| Employee/asset assignment | `ASN-000001` | `assignment` (shared) |

Future modules reuse the same counter (e.g. `work_order` → `WO-000001`).

## Location model

One reusable `locations` table serves projects today and inventory, fuel and
equipment movements tomorrow. `project_id` is nullable: head office, workshop,
warehouse, yard and fuel-storage rows exist without a project, while
`PROJECT_SITE` rows normally reference one. Projects may own many sites;
project and location are never assumed to be the same thing.

## Organization isolation

Every operational row carries `organization_id`. Reads start from
`organization_query()`; related ids (project, location, supervisor, manager,
responsible employee, skill) are re-validated against the caller's organization
on every write, so org A can never reference org B's records. Superusers bypass
permission checks only, never tenant filtering.

## Money, dates, archiving

- Money (`contract_value`, `purchase_price`) is `NUMERIC(18, 2)` / Decimal.
- Timestamps are timezone-aware UTC; business dates (`hire_date`,
  `start_date`, `end_date`) are plain dates.
- Employees, assets, clients and projects archive (`is_active=false`,
  `archived_at`) instead of being deleted; double archive returns 409.
  Assignments and meter readings are immutable history.

## File uploads

`employee_documents` and `asset_documents` accept metadata-only rows
(external `file_url`) or real uploads. Uploaded bytes land in `STORAGE_DIR`
(default `storage/`) namespaced per record
(`employee-documents/<employee_id>/<uuid>.<ext>`), with extension allow-list,
size limit (`MAX_UPLOAD_SIZE_MB`) and path-traversal protection in
`app/core/storage.py`; `file_url` then points at the permission-checked
download endpoint. Swapping in cloud object storage later only requires a new
backend behind the same interface — the API contract is unchanged.
