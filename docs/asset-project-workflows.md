# Asset and project workflow additions

The existing frontend layout, design tokens, employee detail page and multistage employee wizard are preserved.

## Frontend

- Asset rows open `/workspace/assets/{id}` as a full page.
- Asset create/edit forms replace photo URLs with PNG/JPEG uploads. The asset is saved once; upload retries reuse that saved asset.
- Asset profiles show readiness checks, availability, current project/site/operator, specifications, meter/fuel charts, maintenance, fuel logs, meter readings, assignments, inspections, defects, components, documents, insurance, registrations, location/status history and audit activity.
- Assignment and transfer dialogs show the current and destination project, site, operator, handover meter, expected return and reason. Transfers use the existing atomic backend service.
- Maintenance jobs move OPEN → IN_PROGRESS → COMPLETED, with cancellation from an open/in-progress job. Each transition requires notes and is audited.
- Retirement marks equipment out of service and archives it from the active fleet, retaining history. Active assignments and open maintenance must be resolved first.
- Project Equipment adds assignment/transfer and links to full asset pages. Files & Notes supports titled attachments, descriptions, notes and comments, with authenticated downloads.

## Backend

Additive migration `20260910_operational_logs` creates `asset_fuel_logs`, `asset_maintenance_jobs` and `project_records`.

Existing permissions apply: `assets.read` for operating logs, `assets.update` for logging/maintenance, `assets.archive` plus `assets.status.change` for retirement, and `projects.read`/`projects.update` for project collaboration. Existing granular equipment permissions govern other asset actions.

Reads and mutations scope parent IDs and records to the user's organization. Project files use the configured local/Supabase storage backend, bounded upload sizes, allowed extensions, cleanup on transaction failure and authenticated scoped downloads. Money/quantities use Decimal database fields. Asset financial fields remain hidden without `assets.financial.read`.

Fuel logs record refuelling only; they do not automatically issue inventory. Maintenance-job status is separate from operational asset status, which uses the existing status-change workflow. The charts show recorded data; they do not infer fuel efficiency or utilization from missing measurements.

## Validation

- Six backend integration tests passed, including existing equipment transfer/photo tests and new fuel/maintenance/retirement/project-file tests.
- New backend files passed Ruff and Mypy.
- Frontend TypeScript validation passed.
- Migration upgrade → downgrade → upgrade passed on the isolated demo database; the forward migration is applied to the local development database.

The development frontend remains configured for the local backend. No demo records were inserted into the operational database.
