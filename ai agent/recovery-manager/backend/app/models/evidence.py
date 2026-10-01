import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Evidence(Base):
    """
    Evidence entity representing verifiable operational proof.
    Mirrors 'evidence' table from 001_initial_schema.sql.
    """
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("org_id", "evidence_id", name="evidence_org_evidence_id_key"),)

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    evidence_id = Column(Text, nullable=False)
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    unit_id = Column(Text, nullable=True, index=True)
    fnsku = Column(Text, nullable=True, index=True)
    source_manager = Column(Text, nullable=False)
    shipment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sku = Column(Text, nullable=True, index=True)
    asin = Column(Text, nullable=True, index=True)
    evidence_type = Column(Text, nullable=False)
    evidence_content = Column(JSONB, nullable=False)
    evidence_timestamp = Column(DateTime(timezone=True), nullable=False)
    data_origin = Column(Text, nullable=False, default="judge_data", server_default="judge_data")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    shipment = relationship("Shipment", back_populates="evidence")
    order = relationship("Order", back_populates="evidence")
    claim_evidence = relationship("ClaimEvidence", back_populates="evidence")
