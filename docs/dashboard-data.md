# Main dashboard data

The dashboard reads `/api/v1/operations/summary` and `/api/v1/operations/activity`. KPI cards use the nested summary fields, except Available People, which uses `available_employees` rather than the legacy `employees.unassigned` count.

- Active projects: active, non-archived projects with status ACTIVE.
- Active workforce: employees with an active account and ACTIVE employment status.
- Operating assets: active, non-archived equipment with status OPERATING.
- Available people: the same computed availability rules used by the workforce module, including assignments, leave, rotations, training, inactive employment and archival state.
- Available assets: active, non-archived equipment with status AVAILABLE and no active assignment.
- Breakdowns: active, non-archived equipment with status BREAKDOWN.

The older `employees.unassigned` field remains a simple total-minus-assigned count for existing consumers. It must not be labeled as deployment availability. A failed dashboard request displays an error with retry instead of presenting zeroes as measured values.

Recent Activity is a paginated audit-log query, ordered by submission timestamp and ID. It resolves names within the current organization and can recover employee/project/asset references from the associated assignment records for older audit entries. The existing row/detail presentation is retained, with manual refresh and older/newer paging. Timestamps and actor names come from actual audit events.

Only operational events are included. Workforce, equipment, inventory and location events require the corresponding read permissions in addition to dashboard access. Account/security events and unrelated organizations are excluded. Exposed event details are limited to operational names, references, statuses, measurements and dates; private account and personnel fields are not returned by this feed.

Migration `20260912_client_profile_photo` adds the nullable `clients.profile_photo_url` column needed by client-logo reads and uploads. It was applied to the local development database on 2026-09-12; other deployments must run their normal Alembic upgrade before loading the updated client model.
