# Supervisor employee access

An account with the organization-scoped Supervisor role sees employees reporting directly to its linked employee profile, plus employees with an ACTIVE project assignment naming that profile as supervisor. Project assignments must have started and must not have ended. No linked active supervisor profile means an empty team. The superuser bypass is retained; other roles without Supervisor retain existing behavior. Existing permission grants are still required and are not modified.

The request-level ORM policy covers employee lists, counts, profiles, workforce child records, project employee lists, employee-related activity and document discovery. Existing endpoint authorization continues to protect actions. Assignment changes take effect on subsequent reads. Explicit self-service includes the caller's own profile without adding it to the directory. Personal document ownership and Super Private protections remain in place.

Administration is hidden from Supervisor navigation, and its workspace does not mount for those accounts. Contracts and Salaries & Compensation tabs are shown only with their existing document-read and salary-read permissions. These changes do not grant supervisors new sensitive access.

Work Readiness displays `supervisor_name`: the employee's main supervisor, falling back to a supervisor on a current active project assignment. It displays “Not assigned” when neither exists. The name is resolved only after authorizing access to the employee; it does not grant access to the supervisor's complete profile.

No schema migration is required for these changes. Deploy/restart the backend and frontend together. Regression coverage is in `test_supervisor_access.py` and `test_supervisor_scope_unit.py`; PostgreSQL tests require an isolated database ending in `_test`.
