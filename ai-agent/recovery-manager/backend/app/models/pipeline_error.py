import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class PipelineError(Base):
    """
    PipelineError entity representing an AI or DB error during recovery processing.
    Fail-open requirement: captures failed runs as durable records marked 'pending'
    so operators can monitor, query, and retry them.
    """
    __tablename__ = "pipeline_errors"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved', 'ignored')",
            name="chk_pipeline_errors_status",
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    charge_id = Column(
        UUID(as_uuid=True),
        ForeignKey("charges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id = Column(
        Text,
        nullable=False,
        default="org_demo_alpha",
        server_default="org_demo_alpha",
        index=True,
    )
    stage = Column(Text, nullable=False)
    error_reason = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending", server_default="pending", index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # Relationships
    charge = relationship("Charge", backref="pipeline_errors")
