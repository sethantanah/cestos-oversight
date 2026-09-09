# Cestos test workspace

Plain HTML, CSS and JavaScript. No npm install, build step, CDN or framework is required.

1. Configure `.env`, start PostgreSQL, run migrations and seed the administrator as described in the
   root README.
2. Start the API:

   ```powershell
   uv run uvicorn app.main:create_app --factory --reload --no-access-log --no-proxy-headers --loop app.core.event_loop:loop_factory
   ```

   Make sure no older server is still holding port 8000: an outdated instance serves the old
   routes and the new pages will return 404. Restart the server after pulling new backend code.
3. Open **http://localhost:8000/test-ui/** and sign in with your seeded administrator.
   The default organization UUID is prefilled.

The API serves this folder in development/test environments only. It is not mounted in production.
Open it through the API rather than double-clicking index.html or using a separate static server;
requests deliberately use the page's origin to avoid extra CORS configuration.

## What you can do here

- **Overview**: live totals for employees, projects and assets from
  `GET /api/v1/operations/summary`, with cards linking into every domain.
- **Employees**: search, paginated list, create dialog. Select a row for the 360° view:
  current assignment, assignment history, skills, documents — plus forms to assign the
  employee to a project, add a skill and upload a document.
- **Projects**: search, list, create (pick a client). Row detail shows the client, project
  manager, sites, assigned people and assigned equipment.
- **Assets**: search, list, create (pick a category). Row detail shows the current
  assignment, responsible employee, latest meter reading, history, components and
  documents — plus forms to assign the asset, record a meter reading and upload a file.
- **Clients** and **Locations**: lists with create dialogs; client detail lists its
  projects, location detail shows who and what is currently there.
- **Users**: paginated accounts and the create-user dialog from the foundation phase.

Documents uploaded through the UI are stored under the server's `STORAGE_DIR`
(`storage/` by default) and download through permission-checked endpoints, so the
browser never needs direct file-system access.

## Try these flows

- Load any page before signing in: expect a redirect to the sign-in screen.
- Sign in with an incorrect password: expect an error, then retry with correct credentials.
- As the seeded administrator, create an employee, a client, a project for that client
  and a project site (location linked to the project).
- Open the employee, assign them to the project, and see the assignment in the overview.
- Register an asset, assign it to the same project, record a meter reading and upload
  a document; the asset overview should show project, responsible employee and reading.
- Complete the assignment and return the asset: both histories are retained.
- Sign in as an account without roles and open any page: expect permission errors.
- Upload a `.exe` file or one larger than the configured limit: expect a validation error.

Access tokens are held in JavaScript memory. The refresh token is stored in tab-scoped
sessionStorage so reloads restore sign-in through the API. Sign out clears the stored token
and revokes it on the server. Password-reset links skip automatic session restoration. Access-token refresh is automatic.
Requests time out after 15 seconds (30 for uploads/downloads), and failures appear in the notice.
Creating records changes the connected database; destructive deletes are not offered because
operational history is retained by design.

Edit `index.html` for layout, `styles.css` for appearance and `app.js` for behavior. Reload your browser
after edits. Browser developer tools provide additional debugging. No credentials belong in these files.

## Expanded workforce workspace

Employee profiles now expose family, emergency contacts, resumes, documents, qualifications,
skills, training, licences, assignments, rotations and asset authorizations. Available actions
include editing records, verifying documents, choosing primary contacts/current resumes,
completing assignments and retaining archived history. Rotation cycles support creation and
viewing; the backend currently has no cycle update route.

Use workforce filters and summary cards on Employees. Departments, positions, skills and
rotation patterns have setup buttons above the list. Forms use the development API's OpenAPI
schemas for required fields and enum values. Permissions are enforced by the API.

All UI behavior, including Workforce, is bundled in app.js. After updating, reload the page;
if an older page remains cached, use Ctrl+Shift+R. No frontend build is needed.

### New employee onboarding

New employee opens a wide, five-step wizard: personal details, employment, files,
emergency contacts and review. Resume uploads accept PDF/Word; profile photos accept
PNG/JPEG with a preview. Add multiple emergency contacts with full name, address,
relationship and phone; email is optional. The first contact is primary.

Saving creates the employee before uploading files and adding contacts. A partial failure
keeps the wizard open for retry and skips confirmed successful operations. Do not reload
while retrying. Photos use the existing permission-checked employee document storage and
can also be replaced from the employee profile. Uploaded photos appear in Documents.

### Employee pages

The employee list places its title and primary action first, followed by compact summary
counts, collapsible filters/setup and the existing table. Spacing follows a consistent
24px rhythm. Selecting an employee navigates to `#employees/<id>` and renders a flat,
responsive grid of information cards. Related records display their full available fields,
with add/edit/upload actions within each section. The All employees link returns to the
list. Restricted or unavailable sections show their own message without hiding other cards.

## HR and self service

Employee detail cards now include salary history (for authorized HR/finance users) and
linked account administration (superadmins only). Contract reminders supports organization-
wide or employee-specific rules, calendar-month/week/day lead times and multiple recipients.
Notifications and My profile provide in-app reminders and a read-only employee portal.
Email delivery lists queued, sent and failed messages; SMTP configuration is server-side.
See `docs/hr-workflows.md` for permissions, account setup and SMTP settings.


### Activity and leave

My profile lets linked employees log activity notes and optional start/end times, request leave,
and view their own submissions and decisions. No workforce-wide role is needed for self service.
HR employee profiles expose time logs and leave requests; authorized approvers can approve or
reject pending requests. Pending and future leave do not change employment status automatically.
Activity and leave events appear in the employee audit history.

Apply `uv run alembic upgrade head` and restart the API before using these sections. The seed
permission catalog includes `employees.time_log.read/create` and
`employees.leave.read/create/approve/reject`; assign these to appropriate HR roles for managing
other employees. Existing superadmins already have access. Employees can optionally attach a leave letter using the request form. Files use the configured
upload limit and allowed document types; employees and authorized HR users can download them.
