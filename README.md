# Cestos Operations Platform

Backend foundation for Cestos Investments Liberia Incorporated. This phase implements organizations,
users, JWT authentication, refresh-token rotation, permissions, auditing, migrations and development
infrastructure. Operational modules deliberately contain design notes rather than incomplete models.

## Architecture

Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 async sessions, psycopg 3, PostgreSQL and Alembic.
The checked-in `uv.lock` records exact dependency versions. Redis is optional and no application
functionality depends on it yet. Ruff handles formatting and linting; mypy runs in strict mode.

```text
app/
  main.py                 Application factory and lifecycle
  core/                   Settings, security, RBAC dependencies, errors and JSON logging
  db/                     Declarative base, mixins, request sessions
  models/                 Foundation + operational core tables (people, clients,
                          projects, locations, assets, assignments, counters)
  schemas/                Explicit request/response models and pagination
  repositories/           Tenant-scoped reads, no commits
  services/               Auth, users, organizations, audit plus operational
                          use cases (employees, clients, projects, locations,
                          assets, assignments, operations summary)
  api/v1/endpoints/       Thin HTTP handlers
  modules/                Future domain boundaries and relational design notes
  tests/                  Unit and real PostgreSQL integration tests
```

HTTP handlers validate requests and invoke explicit services. Repositories never commit. Auth services
open transaction blocks; user creation completes the transaction already opened by authentication.
An audit mutation is committed atomically with its business mutation. Request sessions rollback on
errors and close after the request. `expire_on_commit=False` prevents implicit async database reads
during response serialization. ORM relationships use explicit eager loading when needed.

## Prerequisites and setup

- Python 3.12 or later and uv
- Docker Desktop/Engine with Compose, or a local PostgreSQL server
- A random JWT signing secret of at least 32 characters

PowerShell examples (POSIX users can use `cp` and `export` equivalents):

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put the generated value into JWT_SECRET_KEY in .env.
# Set INITIAL_ADMIN_EMAIL and a 12–128 character INITIAL_ADMIN_PASSWORD.
uv sync --frozen
uv run pre-commit install
```

`.env` is ignored. The example signing-secret placeholder is intentionally rejected. Production
configuration also rejects debug mode and wildcard CORS. `CORS_ORIGINS` is a JSON array. The initial
currency is USD and timezone is Africa/Monrovia; confirm these company defaults before deployment.

## Docker development

```powershell
docker compose up --build -d
docker compose exec api /srv/cestos/.venv/bin/python -m scripts.seed
# Optional Redis:
docker compose --profile redis up -d redis
```

PostgreSQL persists in the `postgres_data` named volume. API startup waits for PostgreSQL with bounded
retries, applies migrations, then starts Uvicorn. Services bind to loopback on ports 8000, 5432 and
6379. Redis uses an optional profile and is not a dependency of API startup. Stopping the stack with
`docker compose down` preserves the database volume.

For production, run migrations as a separate deployment job before starting API workers using
`uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log --no-proxy-headers --loop app.core.event_loop:loop_factory`.
Do not have multiple workers independently run migrations. The container runs as an unprivileged user.

## Run locally

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run python -m scripts.seed
uv run uvicorn app.main:create_app --factory --reload --no-access-log --no-proxy-headers --loop app.core.event_loop:loop_factory
```

Development API docs: [Swagger UI](http://localhost:8000/docs).
Development test interface: [Cestos workspace](http://localhost:8000/test-ui/). The plain HTML/CSS/JS
in `frontend/` lets you check health, sign in, refresh/logout, list/create/look up users and inspect
redacted API responses. See [frontend guide](frontend/README.md) for testing flows. No build step is
required; this interface is disabled in production.
The explicit event-loop factory supports async psycopg on Windows without deprecated loop policies.
Health: [liveness](http://localhost:8000/health) and [database readiness](http://localhost:8000/health/db).
Database readiness returns 503 when the connection fails. OpenAPI and Swagger UI are disabled when
`APP_ENV=production`. The application lifespan checks database availability before accepting traffic.

## Migrations

```powershell
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe the schema change"
uv run alembic check
uv run alembic upgrade head --sql
```

Review generated revisions, including data backfills and downgrade implications. The initial migration
is a standalone snapshot and does not import mutable application models. `create_all()` is not used.
`updated_at` is maintained by SQLAlchemy writes; direct SQL writers must set it explicitly.

## Seed and authentication

```powershell
uv run python -m scripts.seed
```

The idempotent seed serializes concurrent runs with a PostgreSQL advisory lock. It creates the default
organization, all requested role names and permission codes, and an initial administrator using env
credentials. Existing passwords and role grants are preserved. CEO and Administrator initially have
all permissions; Auditor has read permissions; other roles start with no grants pending policy decisions.
Roles and grants are database records, not permanent hardcoded authorization rules. The seeded
administrator is not a superuser and receives access through the Administrator role.

Default organization ID: `b54b9c8e-f503-4a46-a987-5953c045ff00`.

`POST /api/v1/auth/login` accepts JSON:

```json
{
  "organization_id": "b54b9c8e-f503-4a46-a987-5953c045ff00",
  "email": "admin@example.com",
  "password": "your configured password"
}
```

The response contains `access_token`, `refresh_token`, `token_type` and `expires_in` (seconds).
Send `Authorization: Bearer <access_token>` for authenticated calls. Passwords use Argon2id.
Access tokens validate signature, expiration, issuer, audience, token type, user ID and organization ID.
Current user/organization status and database permissions are checked on each protected request.

| Endpoint | Behavior |
| --- | --- |
| `POST /api/v1/auth/refresh` | JSON `refresh_token`; revokes the old token and returns a new pair |
| `POST /api/v1/auth/logout` | JSON `refresh_token`; idempotent revocation, 204 |
| `GET /api/v1/auth/me` | Current active user, no password fields |
| `GET /api/v1/users?page=1&page_size=20` | Tenant-scoped pagination; requires `users.read` |
| `GET /api/v1/users/{id}` | Tenant-scoped lookup; requires `users.read` |
| `POST /api/v1/users` | Create in caller's tenant; requires `users.create` |
| `GET/POST /api/v1/employees`, `GET/PATCH /api/v1/employees/{id}` | People master data; `employees.read/create/update`, archive via `POST .../archive` (`employees.archive`) |
| `GET/POST /api/v1/employees/{id}/assignments`, `PATCH /api/v1/employee-assignments/{id}` | Assignment history; `employees.assign`; one active assignment per employee |
| `GET/POST /api/v1/employees/{id}/documents`, `GET/POST /api/v1/skills`, `POST /api/v1/employees/{id}/skills` | Documents metadata (`employee_documents.*`) and skills (`skills.*`) |
| `GET/POST /api/v1/clients`, `GET/PATCH /api/v1/clients/{id}` | Clients; `clients.read/create/update` |
| `GET/POST /api/v1/projects`, `GET/PATCH /api/v1/projects/{id}` | Projects; `projects.read/create/update`; sublists `/employees`, `/assets`, `/sites` and `/overview` |
| `GET/POST /api/v1/locations`, `GET/PATCH /api/v1/locations/{id}` | Reusable locations; `locations.read/manage` |
| `GET/POST /api/v1/assets`, `GET/PATCH /api/v1/assets/{id}` | Assets; `assets.read/create/update`, archive via `POST .../archive` |
| `GET/POST /api/v1/assets/{id}/assignments`, `PATCH /api/v1/asset-assignments/{id}` | Asset assignments; `assets.assign`; at most one active per asset |
| `GET/POST /api/v1/assets/{id}/meter-readings` | Meter readings; `assets.record_meter`; decreasing values need `is_correction` + reason |
| `GET/POST /api/v1/asset-categories`, `GET/POST /api/v1/assets/{id}/components` | Categories and lightweight component tracking |
| `GET /api/v1/operations/summary` | Employee/project/asset totals for the first management view |

## Operational core

See [domain model](docs/domain-model.md). Employees, clients, projects, reusable
locations, assets (categories, components, meter readings) and historical
employee/asset assignments form the master operational data. Readable business
numbers (`EMP-`, `CLI-`, `PRJ-`, `SITE-`, `AST-`, `ASN-`) come from an
organization-scoped counter table incremented under row lock — never
`MAX()+1`. Current employee/asset project and location are derived from
`ACTIVE` assignments; nothing denormalizes them. Archiving replaces deletion
for master records. New permissions (`employees.*`, `employee_documents.*`,
`skills.*`, `clients.*`, `projects.*` incl. `assign_people`/`assign_assets`,
`locations.*`, `assets.*` incl. `assign`/`record_meter`/`archive`) are seeded
with defaults per role (Administrator: all; CEO/Auditor: reads; Operations,
Project, Maintenance, HR scoped accordingly). Optional demo data:

```powershell
uv run python -m scripts.seed_demo
```

It creates demo clients, Project Alpha/Bravo, offices/sites, employees,
categories, assets and sample assignments, idempotently and separately from
production seeding. Employee and asset documents accept metadata (`POST
.../documents`) or real file uploads (`POST .../documents/upload`,
multipart, 10 MB default via `MAX_UPLOAD_SIZE_MB`, pdf/png/jpg/doc/xls/txt/csv)
stored under `STORAGE_DIR` (default `storage/`, gitignored) and served through
permission-checked download endpoints (`GET .../documents/{id}/download`).
`app/core/storage.py` isolates the backend so a future cloud store only needs
to implement the same save/resolve interface. Later phases still to come:
maintenance, fuel, inventory, procurement, drilling operations, finance and
forecasting.

Creating users accepts email, password, first_name and last_name; it cannot grant roles or superuser
status. Assigning roles currently requires a reviewed administrative database change. Role-management
endpoints, password resets and user update/archive endpoints are outside this foundation phase.

Refresh tokens are opaque cryptographically random values; only SHA-256 hashes are persisted.
A row lock prevents two simultaneous refreshes from succeeding on the same token. Logout revokes the
submitted refresh token, while issued access tokens remain valid until their short expiry. There is
no refresh-family replay invalidation or logout-all endpoint yet. Clients must store tokens securely;
browser cookie/CSRF integration should be designed with the future frontend. Token responses disable
caching. Add login/refresh rate limiting at the trusted gateway before internet-facing deployment.

## Responses and errors

Responses use Pydantic schemas; lists follow:

```json
{"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0}
```

Pagination is 1-based, defaults to 20 and caps at 100. Errors use:

```json
{"error": {"code": "RESOURCE_NOT_FOUND", "message": "User not found"}}
```

Validation returns 422; missing/invalid authentication 401; denied permission 403; tenant-invisible
records 404; uniqueness conflicts 409; database health failures 503. Unexpected errors return a generic
500 without SQL, stack traces or submitted values. JSON logs include generated request ID, method,
path, status, duration and authenticated user/organization IDs. They omit request bodies, query strings,
authorization headers and secrets. `X-Request-ID` is returned for correlation. Proxy headers are disabled
by default; configure trusted proxies explicitly at deployment if real client IP recording is needed.

## Database design and tenant isolation

One PostgreSQL database, initially the public schema. UUIDs identify entities. Future human-readable
codes such as EMP-00001 remain separate fields. Datetimes are timezone-aware. JSONB holds audit
snapshots and metadata. Database FKs, unique indexes and checks enforce structural integrity.

Users have a lowercase email unique within their organization. Tenant role names are unique per
organization, while system role names use a separate partial unique index. A check ensures only system
roles have a null organization. Association tables have composite primary keys. Authentication resolves
the signed token tenant; `organization_query()` requires a tenant for organization-owned reads.
Superusers bypass permissions only, never tenant filtering. Roles accidentally assigned from a different
organization confer no permissions. Application scoping is the present security boundary; PostgreSQL
row-level security is not enabled. Future relationship writes must validate tenant equality and use
composite tenant foreign keys where possible. Never accept organization ownership from user-create input.

ArchiveMixin provides `is_active` and `archived_at`; ActorMixin provides actor foreign keys. Historical
business records should be archived, not deleted. Audit records retain actor references and have no
mutation/delete API. Use `record_audit()` in the same transaction as CREATE, UPDATE, DELETE, APPROVE,
REJECT, ASSIGN, TRANSFER and ADJUST events. LOGIN/LOGOUT are already audited. Callers must provide only
explicit safe snapshot fields, never secrets. Restricted database privileges and backup retention are
deployment concerns; this foundation does not claim cryptographically tamper-proof audit storage.

## Tests and checks

Unit tests need no running database:

```powershell
uv run pytest -m "not integration"
uv run ruff format --check .
uv run ruff check .
uv run mypy app scripts --exclude app/tests
```

Integration tests use real PostgreSQL and apply the actual Alembic migration. They truncate foundational
tables in a dedicated test database before each test. Never point them at operational data. The guard
requires the test database name to end in `_test` and differ from `DATABASE_URL`'s database name.

```powershell
docker compose -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg://cestos_test:cestos_test_local@localhost:55432/cestos_test"
uv run pytest
# Schema consistency against the migrated TEST database:
$env:DATABASE_URL = $env:TEST_DATABASE_URL
uv run alembic check
docker compose -f docker-compose.test.yml down
```

Use a fresh shell after temporarily overriding `DATABASE_URL`. Without `TEST_DATABASE_URL`, integration
tests explicitly skip. CI should always provision this database and require the full suite. Coverage
includes startup/liveness, DB readiness, login, password rejection, refresh rotation/concurrency,
revocation, active-user enforcement, RBAC denial/success, tenant isolation, create conflicts and atomic
auditing, seed idempotency and database association uniqueness.

## Future roadmap

See [module architecture](app/modules/README.md). The operational core (people,
clients, projects, locations, assets, assignments, operations summary) is
implemented; add incrementally next: inventory and procurement, maintenance and
fuel, drilling operations, then finance and analytics.
Each module can grow local models/schemas/repositories/services/routes while sharing core auth, sessions,
tenant scoping and auditing. Import new models into Alembic metadata discovery and add reviewed migrations.
No operational calculations, dashboards, prediction models or AI are implemented in this phase.

Before production launch, configure managed secrets, TLS, gateway rate limiting, least-privilege database
credentials, backups/restore exercises, monitoring and reviewed role grants. This repository supplies
the application foundation; these environment-specific operational controls require deployment setup.
