import uuid
from decimal import Decimal
from sqlalchemy import Column, Text, Numeric, DateTime, ForeignKey, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Reimbursement(Base):
    """
    Reimbursement entity representing marketplace refunds or offset adjustments.
    Mirrors 'reimbursements' table from 001_initial_schema.sql.
    """
    __tablename__ = "reimbursements"
    __table_args__ = (UniqueConstraint("org_id", "reimbursement_id", name="reimbursements_org_reimbursement_id_key"),)

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    reimbursement_id = Column(Text, nullable=False)
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    charge_id = Column(
        UUID(as_uuid=True),
        ForeignKey("charges.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Monetary precision: Numeric(12, 2) mapped to Python Decimal, never float
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    reimbursement_date = Column(DateTime(timezone=True), nullable=False)
    raw_data = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    data_origin = Column(Text, nullable=False, default="judge_data", server_default="judge_data")

    # Relationships
    charge = relationship("Charge", back_populates="reimbursements")
