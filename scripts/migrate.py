"""
Database migration startup script.

This script handles database readiness checks and runs Alembic migrations
if needed. It's designed to be run before application startup.

Usage:
    python scripts/migrate.py
"""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.database import build_engine, wait_for_database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def check_database_connection() -> bool:
    """Check if database is accessible and ready."""
    logger.info("Checking database connection...")
    settings = get_settings()
    engine = build_engine(settings)
    try:
        await wait_for_database(engine, attempts=20)
        logger.info("✓ Database connection successful")
        return True
    except RuntimeError as exc:
        logger.error(f"✗ Database connection failed: {exc}")
        return False
    finally:
        await engine.dispose()


def get_migration_status() -> tuple[str | None, str | None]:
    """
    Get current migration status.
    
    Returns:
        Tuple of (current_revision, head_revision) or (None, None) if error
    """
    logger.info("Checking migration status...")
    
    try:
        # Get current database revision
        current_result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            capture_output=True,
            text=True,
            check=False,
        )
        current = current_result.stdout.strip() if current_result.returncode == 0 else None
        
        # Get head revision
        heads_result = subprocess.run(
            [sys.executable, "-m", "alembic", "heads"],
            capture_output=True,
            text=True,
            check=False,
        )
        heads = heads_result.stdout.strip() if heads_result.returncode == 0 else None
        
        if current and heads:
            logger.info(f"Current revision: {current}")
            logger.info(f"Head revision: {heads}")
        
        return current, heads
    except Exception as exc:
        logger.error(f"Failed to check migration status: {exc}")
        return None, None


def run_migrations() -> bool:
    """
    Run pending Alembic migrations.
    
    Returns:
        True if successful, False otherwise
    """
    logger.info("Running database migrations...")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=False,
        )
        
        if result.returncode == 0:
            logger.info("✓ Database migrations completed successfully")
            return True
        else:
            logger.error(f"✗ Database migrations failed with exit code {result.returncode}")
            return False
    except Exception as exc:
        logger.error(f"✗ Failed to run migrations: {exc}")
        return False


async def migrate() -> int:
    """
    Main migration workflow.
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    logger.info("Starting database migration process...")
    
    # Step 1: Check database connection
    if not await check_database_connection():
        logger.error("Cannot proceed without database connection")
        return 1
    
    # Step 2: Check migration status
    current, heads = get_migration_status()
    
    if current is None or heads is None:
        logger.warning("Could not determine migration status, attempting migrations anyway")
        if not run_migrations():
            return 1
    elif current == heads:
        logger.info("✓ Database is up to date, no migrations needed")
    else:
        logger.info("Pending migrations detected, running migrations...")
        if not run_migrations():
            return 1
    
    logger.info("✓ Database migration process completed successfully")
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(migrate())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Migration interrupted by user")
        sys.exit(130)
    except Exception as exc:
        logger.exception(f"Unexpected error during migration: {exc}")
        sys.exit(1)
