# Database Migration Guide

This document explains how to use the database migration scripts to ensure your database is always up to date.

## Overview

The Cestos platform uses **Alembic** for database schema migrations. There are multiple ways to run migrations depending on your deployment scenario.

## Migration Scripts

### 1. `scripts/migrate.py` (Recommended for Development)

The primary migration script with status checking and detailed logging.

**Features:**
- ✓ Waits for database availability (20 attempts)
- ✓ Checks migration status before running
- ✓ Only runs migrations if needed
- ✓ Detailed logging for debugging
- ✓ Proper error handling

**Usage:**
```bash
# Run migrations before starting the app
python scripts/migrate.py

# Check exit code (0 = success, 1 = failure)
echo $?
```

**Example Output:**
```
2026-09-09 10:30:45,123 - migrate - INFO - Starting database migration process...
2026-09-09 10:30:45,234 - migrate - INFO - Checking database connection...
2026-09-09 10:30:45,345 - migrate - INFO - ✓ Database connection successful
2026-09-09 10:30:45,456 - migrate - INFO - Checking migration status...
2026-09-09 10:30:45,567 - migrate - INFO - Current revision: 20260909_inventory
2026-09-09 10:30:45,678 - migrate - INFO - Head revision: 20260909_inventory
2026-09-09 10:30:45,789 - migrate - INFO - ✓ Database is up to date, no migrations needed
2026-09-09 10:30:45,890 - migrate - INFO - ✓ Database migration process completed successfully
```

### 2. `scripts/start.py` (Application Startup)

The main application startup script that automatically runs migrations before starting the app.

**Features:**
- ✓ Automatically runs migrations via `scripts/migrate.py`
- ✓ Aborts if migrations fail
- ✓ Starts the FastAPI application on `0.0.0.0:8000`

**Usage:**
```bash
# Start the application (migrations run automatically)
python scripts/start.py
```

This is the recommended way to start the application locally.

### 3. `scripts/migrate_docker.py` (Docker/Kubernetes)

Optimized migration script for containerized deployments.

**Features:**
- ✓ Optimized for CI/CD pipelines
- ✓ Configurable retry attempts
- ✓ Verbose logging for containers
- ✓ Specific exit codes for different failure modes
- ✓ Structured logging format

**Exit Codes:**
- `0` - Success
- `1` - Database connection failed
- `2` - Migration failed
- `130` - User interrupt (Ctrl+C)

**Usage:**
```bash
# In Docker/Kubernetes
python scripts/migrate_docker.py

# In docker-compose.yml
services:
  app:
    build: .
    command: |
      sh -c "python scripts/migrate_docker.py && \
             uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"
```

## Manual Alembic Commands

While the migration scripts handle most scenarios, you can also use Alembic directly for advanced operations.

### Check Current Migration Status
```bash
# Show current database revision
alembic current

# Show all available revisions
alembic heads

# Show migration history
alembic history --verbose
```

### Run Migrations
```bash
# Apply all pending migrations (what our scripts do)
alembic upgrade head

# Apply a specific number of migrations
alembic upgrade +1
alembic upgrade +2

# Rollback to specific revision
alembic downgrade <revision>

# Rollback one migration
alembic downgrade -1
```

### Create New Migrations
```bash
# Auto-detect schema changes (recommended)
alembic revision --autogenerate -m "describe your changes"

# Manual empty migration
alembic revision -m "describe your changes"

# After creating, review the migration file in alembic/versions/
# Then run: alembic upgrade head
```

## Deployment Scenarios

### Local Development
```bash
# Terminal 1: Start the application
python scripts/start.py

# Or manually run migrations first
python scripts/migrate.py
# Then start app
python -m uvicorn app.main:create_app --factory --reload
```

### Docker Container (Recommended)
```dockerfile
# In Dockerfile after dependencies are installed
RUN python scripts/migrate_docker.py
CMD ["python", "scripts/start.py"]
```

Or using docker-compose:
```yaml
services:
  app:
    build: .
    environment:
      - DATABASE_URL=postgresql+psycopg://user:password@db:5432/cestos
    depends_on:
      db:
        condition: service_healthy
    command: python scripts/start.py
```

### Kubernetes Job (Pre-deployment)
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: cestos:latest
        command: ["python", "scripts/migrate_docker.py"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
      restartPolicy: Never
```

### CI/CD Pipeline (GitHub Actions Example)
```yaml
- name: Run database migrations
  run: |
    python scripts/migrate_docker.py
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

## Troubleshooting

### Migration Fails - "Database connection failed"
**Problem:** Cannot connect to PostgreSQL
```bash
# Solution: Check database connection string
echo $DATABASE_URL

# Ensure database is running
psql $DATABASE_URL -c "SELECT 1"

# Increase retry attempts by editing migrate_docker.py
# max_retries parameter (default: 30 attempts)
```

### Migration Fails - "Current migration state unknown"
**Problem:** Migration tracking is corrupted
```bash
# View migration history
alembic history --verbose

# Check alembic_version table
psql $DATABASE_URL -c "SELECT * FROM alembic_version;"

# For recovery (rare), you may need to manually update:
# psql $DATABASE_URL -c "UPDATE alembic_version SET version_num = '<revision_id>';"
```

### Migration Fails - "Column already exists"
**Problem:** Schema drift between database and migration files
```bash
# Approach 1: Create new migration to idempotent state
alembic revision --autogenerate -m "fix schema drift"
alembic upgrade head

# Approach 2: Downgrade and re-apply
alembic downgrade <previous_working_revision>
alembic upgrade head
```

### Application Starts But Database Schema Is Old
**Problem:** Migrations didn't run
```bash
# Run migrations manually
python scripts/migrate.py

# Check if it reports "Database is up to date" or runs migrations
# If it says "up to date" but schema is old, the alembic_version table
# may be out of sync - see "Current migration state unknown" above
```

## Best Practices

1. **Always test migrations locally first**
   ```bash
   # Test against a local PostgreSQL instance
   python scripts/migrate.py
   ```

2. **Review auto-generated migrations**
   - Check the migration file in `alembic/versions/`
   - Ensure it matches your intended schema changes
   - Edit if needed before applying

3. **Use descriptive migration messages**
   ```bash
   alembic revision --autogenerate -m "add users.phone_number column"
   ```

4. **Keep migrations small and focused**
   - One logical change per migration
   - Easier to debug and rollback if needed

5. **Test rollbacks in development**
   ```bash
   # Apply a migration
   alembic upgrade +1
   
   # Test the app works with the change
   # Then rollback to verify it works
   alembic downgrade -1
   ```

6. **Never edit migration files manually** after they're created
   - Create a new migration instead
   - This maintains a consistent history

## Development Workflow

1. Make schema changes in `app/models/` files
2. Generate migration:
   ```bash
   alembic revision --autogenerate -m "describe change"
   ```
3. Review generated migration file
4. Test locally:
   ```bash
   alembic upgrade head
   python scripts/start.py
   ```
5. Commit both model changes and migration file to git
6. On deploy, migrations run automatically via the startup scripts

## Additional Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy ORM Guide](https://docs.sqlalchemy.org/en/20/orm/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
