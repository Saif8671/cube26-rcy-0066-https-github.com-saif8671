import uuid
from decimal import Decimal
from enum import Enum
from sqlalchemy import Column, Text, Numeric, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class AssessmentOutcome(str, Enum):
    """The four valid assessment states under the 'Evidence first, claim second' principle."""
    CONTRADICTED = "CONTRADICTED"
    SUPPORTED = "SUPPORTED"
    SILENT = "SILENT"
    UNCERTAIN = "UNCERTAIN"


class Claim(Base):
    """
    Claim entity representing an auditable dispute evaluation against an imposed charge.
    Mirrors 'claims' table from 001_initial_schema.sql.
    """
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("org_id", "claim_id", name="claims_org_claim_id_key"),
        CheckConstraint(
            "assessment IN ('CONTRADICTED', 'SUPPORTED', 'SILENT', 'UNCERTAIN')",
            name="claims_assessment_check",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="claims_confidence_check",
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    claim_id = Column(Text, nullable=False)
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    charge_id = Column(
        UUID(as_uuid=True),
        ForeignKey("charges.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assessment = Column(Text, nullable=False)
    # Monetary precision: Numeric(12, 2) mapped to Python Decimal, never float
    claim_amount = Column(Numeric(precision=12, scale=2), nullable=True)
    confidence = Column(Numeric(precision=5, scale=4), nullable=True)
    explanation = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW")
    source_manager = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    data_origin = Column(Text, nullable=False, default="judge_data", server_default="judge_data")

    # Relationships
    charge = relationship("Charge", back_populates="claims")
    claim_evidence = relationship("ClaimEvidence", back_populates="claim")
