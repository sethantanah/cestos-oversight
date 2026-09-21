import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.router import router
from app.api.v1.endpoints.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.database import build_engine, wait_for_database
from app.core.exceptions import install_exception_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.storage import build_storage


def create_app(settings: Settings | None = None) -> FastAPI:
    from app.services import document_registry  # noqa: F401
    from app.services import employee_access  # noqa: F401

    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await wait_for_database(engine)
            try:
                async with engine.begin() as conn:
                    from app.models import Base
                    await conn.run_sync(Base.metadata.create_all)
            except Exception:
                pass
            from app.services.document_index import worker
            from app.services.document_registry import backfill_registry

            try:
                async with app.state.session_factory() as catalog_session:
                    await backfill_registry(catalog_session)
                    if hasattr(app.state.storage, "ensure_private"):
                        from sqlalchemy import select
                        from starlette.concurrency import run_in_threadpool

                        from app.models.document_library import LibraryDocument

                        paths = (
                            await catalog_session.scalars(select(LibraryDocument.storage_path))
                        ).all()
                        for document_path in paths:
                            await run_in_threadpool(app.state.storage.ensure_private, document_path)
            except Exception as exc:
                import structlog

                structlog.get_logger().warning("startup_catalog_init_failed", error=str(exc))
            indexing_task = asyncio.create_task(worker(app)) if settings.app_env != "test" else None
            from app.services.mail import scheduler

            task = (
                asyncio.create_task(scheduler(app))
                if settings.scheduler_enabled and settings.app_env != "test"
                else None
            )
            try:
                yield
            finally:
                if indexing_task:
                    indexing_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await indexing_task
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
    app.state.storage = build_storage(settings)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    install_exception_handlers(app)
    app.include_router(router)
    app.include_router(health_router)
    return app
