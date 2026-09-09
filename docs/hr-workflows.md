# HR contracts, compensation and employee accounts

## Contracts and alerts

Employee documents with type `EMPLOYMENT_CONTRACT` and an expiry date drive reminders.
The legacy employee `contract_end_date` is descriptive; it does not override a document's
expiry date. Archive superseded contracts to stop future reminders. Rejected and archived
documents are excluded. An active rule can cover everyone or one employee, with a lead
value in days, weeks or calendar months, and selected active users in the same organization.
Month subtraction clamps to month-end (March 31 minus one month is February 28/29).

The API runs the scheduler every 60 seconds by default, using UTC dates. It catches up on
due/overdue active contracts after downtime. A PostgreSQL advisory lock and unique delivery
key prevent duplicate in-app notifications for a rule/document/expiry/recipient. Renewing a
contract's expiry date creates a new reminder cycle. Use separate rules for separate warning
thresholds (e.g. 90 days and one month). Pausing a rule stops new reminders; existing in-app
notifications and queued mail are retained. `POST /api/v1/hr/alert-rules/run` runs a tenant's
rules immediately. Production can disable the embedded scheduler via SCHEDULER_ENABLED.

Recipients get an in-app notification and a durable email queue entry. SMTP configuration:

```dotenv
SMTP_HOST=mail.example.com
SMTP_PORT=587
SMTP_USERNAME=cestos
SMTP_PASSWORD=your-secret
SMTP_FROM=hr@example.com
SMTP_STARTTLS=true
PUBLIC_BASE_URL=https://your-frontend.example.com
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=60
```

Put real credentials in the server environment or local `.env`, never source control.
PUBLIC_BASE_URL is the frontend URL, not the API root. The bundled local UI is development/
test only; a production frontend must implement the same `#reset=` flow or use the reset API.
No credentials have been invented or configured. Queue entries stay pending until SMTP_HOST
and SMTP_FROM exist. Failures retry with exponential backoff; after ten attempts, an HR
administrator can retry from Email delivery. SMTP has at-least-once delivery: a crash after
SMTP acceptance but before database commit can cause a duplicate email. In-app alerts remain
deduplicated. The worker checks active recipients and organizations before sending.

## Salaries

Salary history is mapped to an employee and includes exact decimal amount, currency, pay
period, effective start/end dates and restricted HR notes. Effective periods are inclusive
and cannot overlap; end the existing period before adding the next one. Amounts and history
cannot be overwritten or deleted through the API. This is compensation history, not payroll
calculation, taxation, payslips or payment processing.

## Account lifecycle

Creating an employee uses work email, falling back to personal email. No email means no
account. A matching active user in the SAME organization is linked; their password and roles
are preserved. An account already linked to another employee is rejected. New accounts have
no HR/admin grants, a unique random unusable initial password, and a queued setup email.
There is no shared default password. Setup links last 24 hours, are single-use, and require a
password of at least 12 characters. Only token hashes are persisted; raw tokens are generated
for SMTP delivery and never stored in the mail queue or application logs.

Existing employees are not silently backfilled. Superadmins can use Link or create account
on an employee profile. Only `users.is_superuser = true` can change linked account emails or
request password resets. Normal HR employee editing cannot bypass this workflow. Email
collisions are rejected, never merged. Email changes/reset requests invalidate access and
refresh tokens, require setup again, and queue an email to the new/current address.

`Administrator` is an organization role, not automatically a superadmin. This migration
introduces salary grants for Administrator/CEO/HR/Finance and alert management for
Administrator/CEO/HR. It does not promote accounts to superadmin or grant new employee roles.

## Self service and privacy

My profile uses an ownership-scoped API independent of HR permissions. Employees can read
their own personal/contact/employment details, emergency contacts, salary amount/history,
contracts, qualifications, training, licences and assignments. Contract downloads check
employee ownership, organization and active document status. There are no self-service write
routes. Salary notes, HR notes, family records and audit history are excluded via explicit
field allowlists. Archived employees cannot use self service. Existing privileged roles keep
their authorized HR access; linking never removes or adds those roles. Basic employee read
now redacts private master fields. HR responses use `Cache-Control: no-store`.

## Local rollout and checks

Run `alembic upgrade head`, then restart the API. The migration adds employee-user linkage,
salary history, reminder rules, notifications, password setups, SMTP queue and session-version
fields. It preserves employee and document records. No external email is sent without SMTP
configuration. See `app/tests/test_hr.py` for ownership, setup/reset, tenant isolation, salary
dates, reminder deduplication and SMTP retry regression tests.

Validation for this change: full backend regression run 62 passed; final HR/security rerun
7 passed (including the added basic-read privacy test). Strict mypy passed for 73 source
files; Ruff passed; Alembic reported no pending model changes. UI checks covered salary
controls, reminder recipient selection, read-only self-service, employee details and the
onboarding wizard. Live SMTP delivery remains untested because SMTP is not configured.
