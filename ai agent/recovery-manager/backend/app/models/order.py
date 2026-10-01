import uuid
from sqlalchemy import Column, Text, DateTime, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Order(Base):
    """
    Order entity representing an external marketplace customer/transfer order.
    Mirrors 'orders' table from 001_initial_schema.sql.
    """
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("org_id", "order_id", name="orders_org_order_id_key"),)

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    order_id = Column(Text, nullable=False)
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    charges = relationship("Charge", back_populates="order")
    evidence = relationship("Evidence", back_populates="order")
