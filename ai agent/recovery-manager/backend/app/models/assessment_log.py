import uuid
from decimal import Decimal
from sqlalchemy import Column, Text, Numeric, Boolean, DateTime, ForeignKey, CheckConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class AssessmentLog(Base):
    """
    AssessmentLog entity representing an immutable audit trail of every charge evaluation.
    Mirrors 'assessment_log' table from 002_assessment_log.sql.
    """
    __tablename__ = "assessment_log"
    __table_args__ = (
        CheckConstraint(
            "assessment IN ('CONTRADICTED', 'SUPPORTED', 'SILENT', 'UNCERTAIN')",
            name="assessment_log_assessment_check",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="assessment_log_confidence_check",
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    charge_id = Column(
        UUID(as_uuid=True),
        ForeignKey("charges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assessment = Column(Text, nullable=False, index=True)
    claim_supported = Column(Boolean, nullable=False, default=False)
    claim_amount = Column(Numeric(precision=12, scale=2), nullable=True)
    confidence = Column(Numeric(precision=5, scale=4), nullable=True)
    reason = Column(Text, nullable=True)
    evidence_ids = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    charge = relationship("Charge", back_populates="assessment_logs")
