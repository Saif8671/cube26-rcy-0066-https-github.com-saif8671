from fastapi import FastAPI
from app.api import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import logger


def create_application() -> FastAPI:
    """Application factory for Recovery Manager Backend."""
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Recovery Manager Backend API — Evidence-first financial recovery "
            "system for ecommerce sellers."
        ),
        docs_url="/docs" if settings.backend_env != "production" else None,
        redoc_url="/redoc" if settings.backend_env != "production" else None,
    )

    # Add CORS Middleware with environment-driven allowed origins (maintains dev compatibility)
    from fastapi.middleware.cors import CORSMiddleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register centralized error handlers
    register_error_handlers(application)

    # Register API routers (health, etc.)
    application.include_router(api_router)

    logger.info(f"Initialized {settings.app_name} v{settings.app_version} in {settings.backend_env} mode.")
    return application


app = create_application()
