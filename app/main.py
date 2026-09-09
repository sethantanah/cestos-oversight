import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.router import router
from app.api.v1.endpoints.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.database import build_engine, wait_for_database
from app.core.exceptions import install_exception_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.storage import LocalStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await wait_for_database(engine)
            from app.services.mail import scheduler

            task = (
                asyncio.create_task(scheduler(app))
                if settings.scheduler_enabled and settings.app_env != "test"
                else None
            )
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
        finally:
            await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        debug=False,
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.storage = LocalStorage(
        Path(settings.storage_dir), settings.max_upload_size_mb * 1024 * 1024
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    install_exception_handlers(app)
    app.include_router(router)
    app.include_router(health_router)
    frontend = Path(__file__).resolve().parent.parent / "frontend"
    if settings.app_env != "production" and frontend.is_dir():
        app.mount("/test-ui", StaticFiles(directory=frontend, html=True), name="test-ui")
    return app
