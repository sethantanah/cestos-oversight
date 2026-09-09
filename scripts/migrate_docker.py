"""
Docker/Kubernetes migration runner.

This script is optimized for containerized deployments where migrations
should be run as a separate job before the application starts.

Usage in Docker:
    # In docker-compose.yml or Kubernetes Job
    python scripts/migrate_docker.py

Exit codes:
    0 - Success
    1 - Database connection failed
    2 - Migration failed
    130 - User interrupt
"""

import asyncio
import logging
import subprocess
import sys
from time import sleep

from app.core.config import get_settings
from app.core.database import build_engine, wait_for_database

# Configure structured logging for container environments
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migration")


async def ensure_database_ready(max_retries: int = 30) -> bool:
    """
    Wait for database to be ready with exponential backoff.
    
    Args:
        max_retries: Maximum connection attempts
        
    Returns:
        True if database is ready, False otherwise
    """
    logger.info("Waiting for database to be ready...")
    settings = get_settings()
    engine = build_engine(settings)
    
    try:
        await wait_for_database(engine, attempts=max_retries)
        logger.info("Database is ready")
        return True
    except RuntimeError as exc:
        logger.error(f"Database failed to become available: {exc}")
        return False
    finally:
        await engine.dispose()


def run_migrations() -> bool:
    """
    Run Alembic migrations with detailed output.
    
    Returns:
        True if successful, False otherwise
    """
    logger.info("Starting database migrations...")
    
    try:
        # Run with verbose output for better debugging
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head", "-v"],
            check=False,
        )
        
        if result.returncode == 0:
            logger.info("Successfully applied all pending migrations")
            return True
        else:
            logger.error(f"Migration failed with exit code {result.returncode}")
            return False
            
    except Exception as exc:
        logger.error(f"Unexpected error running migrations: {exc}")
        return False


async def main() -> int:
    """
    Main migration entry point optimized for containers.
    
    Returns:
        Exit code (0=success, 1=db error, 2=migration error, 130=interrupt)
    """
    logger.info("=== Database Migration Process ===")
    
    # Step 1: Ensure database is ready
    if not await ensure_database_ready():
        logger.error("Cannot proceed - database is unavailable")
        return 1
    
    # Step 2: Run migrations
    if not run_migrations():
        logger.error("Migration process failed")
        return 2
    
    logger.info("=== Migration Process Complete ===")
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("Migration interrupted by user")
        sys.exit(130)
    except Exception as exc:
        logger.exception(f"Fatal error: {exc}")
        sys.exit(2)
