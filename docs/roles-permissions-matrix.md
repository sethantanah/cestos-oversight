# Roles and Permissions Matrix

The Administration matrix now separates sensitive employee access into read and write controls:

- `employees.contracts.read` — view employment contracts (mapped to the existing document-read permission).
- `employees.contracts.write` — upload, update, or archive employment contracts (mapped to document management).
- `employees.salary.read` — view salary and compensation records.
- `employees.salary.write` — create or close salary periods (mapped to the existing salary-management permission).

The existing `employees.contracts.manage` and `employees.salary.manage` permissions remain valid for compatibility. A user may see their own contract through the normal self-service route even when they do not have organization-wide sensitive-read access; the new contract-read permission governs other employee contracts.

The matrix also exposes scope controls for role configuration: `projects.read_assigned`, `assets.read_assigned`, and `inventory.read_assigned`. These are mapped to their domain read permissions while preserving assignment-scoped behavior. `projects.read_all` is the explicit widening permission; without it, project reads remain assignment restricted. Asset and inventory endpoints should use the corresponding assigned-scope permissions when their team/store assignment filtering is enabled.

The Roles tab has a search field that filters by category, display name, code, and description. It reuses the existing role-permission update endpoint, so changes remain auditable and take effect immediately.
