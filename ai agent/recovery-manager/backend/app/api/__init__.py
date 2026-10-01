"""API router aggregation."""

from fastapi import APIRouter
from app.api.routes.health import router as health_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.ai import router as ai_router
from app.api.routes.rules import router as rules_router
from app.api.routes.claims import router as claims_router
from app.api.routes.charges import router as charges_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.pipeline import router as pipeline_router
from app.api.routes.recovery import router as recovery_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(ingestion_router)
api_router.include_router(evidence_router)
api_router.include_router(ai_router)
api_router.include_router(rules_router)
api_router.include_router(claims_router)
api_router.include_router(charges_router)
api_router.include_router(dashboard_router)
api_router.include_router(pipeline_router)
api_router.include_router(recovery_router)

__all__ = ["api_router"]

