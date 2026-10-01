from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings
from app.core.logging import logger


def register_error_handlers(app: FastAPI) -> None:
    """Register centralized exception handlers for FastAPI application."""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder({
                "error": "Validation Error",
                "message": "The request body or parameters failed validation.",
                "details": exc.errors(),
            }),
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        logger.exception(
            "database error method=%s path=%s type=%s message=%s sql=%s",
            request.method,
            request.url.path,
            type(exc).__name__,
            str(exc),
            getattr(exc, "statement", None),
        )
        # Never expose raw SQL queries or DB connection details to clients
        reason_code = "DATABASE_ERROR"
        if request.url.path == "/recovery/run":
            reason_code = "RECOVERY_DATABASE_ERROR"
        elif request.url.path == "/recovery/preview":
            reason_code = "RECOVERY_PREVIEW_DATABASE_ERROR"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Database Error",
                "reason_code": reason_code,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
        content = {
            "error": "Internal Server Error",
            "message": "An unexpected error occurred.",
        }
        # In development mode, provide error class for debugging without exposing secrets
        if settings.backend_env == "development":
            content["debug_error_type"] = exc.__class__.__name__

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=content,
        )
