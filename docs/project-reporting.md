# Project dashboard and field updates

The main Projects link opens `/projects-overview`: portfolio KPIs followed by a paginated project register. All projects remains at `/workspace/projects`, with search, status filtering, sorting within the current page, and CSV export of that page. Opening a project navigates to `/project-command-center?project=<id>`.

The command center includes project editing (including manager and drilling target), employee assignment/transfer, project-assignment supervisor changes, equipment, inventory, sites, files/notes, Updates, and Activity. Employee transfers use the existing atomic transfer API. Supervisor changes affect the selected project assignment.

## Reports and KPI definitions

Updates require an active project site, report type, reporting date, and title. Types are drilling update, progress update, safety report, and site issue. Notes and one file are optional. Drilling updates also require nonnegative meters, an integer hole count, and average depth in meters. Future dates are rejected.

Each report records incremental work for its reporting period, not project-to-date totals. Cumulative meters and holes are summed; average depth is weighted by hole count. Reports with zero holes do not affect the weighted depth. Non-drilling reports contribute to report counts but not drilling totals. Target progress is cumulative meters divided by the project's configured target, and may exceed 100%. Without a target, no percentage is calculated. Monthly metrics show the latest 12 months containing drilling reports.

The portfolio's total/status counts exclude archived projects. Its drilling totals cover all submitted reports, including historical projects. Attention counts cover active/mobilizing projects: those past their expected end date, and those without a report dated within the last seven days.

Reports are immutable submissions. The authenticated user ID, author name, site name, submission time, reporting date, measurements, and optional attachment metadata are retained. A `project.report_created` audit event is committed in the same transaction. Project and assignment edits record before/after values. The Activity tab also includes existing project-linked assignment and collaboration events.

## API and deployment

Apply migration `20260912_project_reports` with `alembic upgrade head` when deploying the backend, before serving the new reporting UI. Use the application's existing storage backend and upload limits; attachment paths are never exposed in API responses. The migration was verified against the isolated test database and applied to the local development database on 2026-09-12. Production deployment still requires the migration.

- `GET /api/v1/projects/dashboard-summary`
- `GET /api/v1/projects/{id}/report-metrics`
- `GET /api/v1/projects/{id}/reports` (pagination, report type and site filters)
- `POST /api/v1/projects/{id}/reports` (multipart `report` JSON plus optional `file`)
- `GET /api/v1/projects/{id}/reports/{report_id}/attachment`
- `GET /api/v1/projects/{id}/activity` (pagination)

Reads require `projects.read`; report submission requires `projects.update`. Assignment, transfer, project editing, and site creation keep their existing permissions. Every report, metric, attachment and activity query is scoped to the authenticated organization and project. An upload is removed if its database transaction fails.

Validation: `app/tests/test_project_reports.py` covers field validation, report aggregation, weighted depth, target progress, attachments, attribution, pagination/filtering, audit entries, permission checks, and organization/project isolation. Run it alongside `test_operational.py` and `test_workforce_ops.py` with `TEST_DATABASE_URL` set to an isolated PostgreSQL database ending in `_test`.
