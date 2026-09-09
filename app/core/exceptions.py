import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException


class AppError(Exception):
    status = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str) -> None:
        self.message = message


class NotFoundError(AppError):
    status = 404
    code = "RESOURCE_NOT_FOUND"


class ConflictError(AppError):
    status = 409
    code = "CONFLICT"


class ForbiddenError(AppError):
    status = 403
    code = "FORBIDDEN"


class AuthenticationError(AppError):
    status = 401
    code = "AUTHENTICATION_FAILED"


class ValidationError(AppError):
    status = 422
    code = "VALIDATION_ERROR"


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers={"WWW-Authenticate": "Bearer"} if status == 401 else None,
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "VALIDATION_ERROR", "Request validation failed")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        return error_response(409, "CONFLICT", "The request conflicts with existing data")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        structlog.get_logger().error("unhandled_error", error_type=type(exc).__name__)
        return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")
