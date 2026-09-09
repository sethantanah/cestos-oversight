"""Real process startup smoke check, in addition to in-process ASGI tests."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_uvicorn_startup(database_url: str, tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env.update(
        DATABASE_URL=database_url,
        JWT_SECRET_KEY="a-test-only-secret-that-is-over-32-characters",
        APP_ENV="test",
    )
    with (tmp_path / "server.log").open("w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
                "--no-proxy-headers",
                "--loop",
                "app.core.event_loop:loop_factory",
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        pytest.fail(f"Uvicorn exited during startup: {log.read()}")
                    try:
                        response = client.get("/health/db")
                        assert response.status_code == 200
                        assert response.json() == {"status": "ok"}
                        break
                    except httpx.TransportError:
                        time.sleep(0.2)
                else:
                    pytest.fail("Uvicorn did not become ready within 30 seconds")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
