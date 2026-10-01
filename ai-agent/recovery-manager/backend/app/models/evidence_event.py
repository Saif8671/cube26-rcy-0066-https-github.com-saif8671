import uuid
from sqlalchemy import Column, DateTime, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base


class EvidenceEvent(Base):
    """
    EvidenceEvent entity representing operational evidence records
    (receiving, prep, pack, return, status) matched against financial charges.
    Mirrors 'evidence_events' table from 005_evidence_events.sql.
    """
    __tablename__ = "evidence_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    shipment_id = Column(Text, nullable=False, index=True)
    evidence_type = Column(Text, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(Text, nullable=True)
    source_file = Column(Text, nullable=False, default="", server_default="")
    raw_payload = Column(JSONB, nullable=False, default=dict, server_default="{}" )
    idempotency_key = Column(Text, nullable=True, unique=True, index=True)
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
