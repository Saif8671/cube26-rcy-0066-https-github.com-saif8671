import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Override(Base):
    """
    Override audit entity representing a human operator override disagreeing with the AI agent.
    Never update or delete rows in this table — append only.
    """
    __tablename__ = "overrides"
    __table_args__ = (
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="chk_overrides_non_empty_reason",
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
    claim_id = Column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    org_id = Column(
        Text,
        nullable=False,
        default="org_demo_alpha",
        server_default="org_demo_alpha",
        index=True,
    )
    original_assessment = Column(Text, nullable=True)
    original_status = Column(Text, nullable=True)
    new_verdict = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    reviewer_id = Column(Text, nullable=False, default="operator")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # Relationships
    charge = relationship("Charge", backref="overrides")
    claim = relationship("Claim", backref="overrides")
