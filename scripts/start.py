"""Single-instance development entry point with integrated database migration."""

import subprocess
import sys

import uvicorn

from app.core.event_loop import loop_factory


if __name__ == "__main__":
    # Run database migrations before starting the application
    # This ensures the database schema is up to date
    print("Running database migrations...")
    migration_result = subprocess.run([sys.executable, "scripts/migrate.py"], check=False)
    
    if migration_result.returncode != 0:
        print("Database migration failed. Aborting startup.")
        sys.exit(1)
    
    print("Starting Cestos application...")
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        access_log=False,
        proxy_headers=False,
        loop="app.core.event_loop:loop_factory",
    )
