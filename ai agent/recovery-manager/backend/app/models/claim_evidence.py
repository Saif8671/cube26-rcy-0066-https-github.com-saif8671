import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class ClaimEvidence(Base):
    """
    Join entity enforcing many-to-many traceable audit links between claims and evidence.
    Mirrors 'claim_evidence' table from 001_initial_schema.sql.
    """
    __tablename__ = "claim_evidence"
    __table_args__ = (
        UniqueConstraint("claim_id", "evidence_id", name="uq_claim_evidence"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    claim_id = Column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    claim = relationship("Claim", back_populates="claim_evidence")
    evidence = relationship("Evidence", back_populates="claim_evidence")
