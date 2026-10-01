"""Business logic services namespace."""

from app.services.evidence_engine import (
    EvidenceEngine,
    evidence_engine,
    EvidenceMatch,
    EvidenceRetrievalResult,
    EvidenceEngineError,
    ChargeNotFoundError,
)
from app.services.pipeline import (
    process_charge_pipeline,
)
from app.schemas.pipeline import (
    PipelineResult,
)

__all__ = [
    "EvidenceEngine",
    "evidence_engine",
    "EvidenceMatch",
    "EvidenceRetrievalResult",
    "EvidenceEngineError",
    "ChargeNotFoundError",
    "process_charge_pipeline",
    "PipelineResult",
]

