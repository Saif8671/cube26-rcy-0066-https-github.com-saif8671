import uuid
from decimal import Decimal
from sqlalchemy import Column, Text, Numeric, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from app.core.database import Base


class Charge(Base):
    """
    Charge entity representing a marketplace fee or discrepancy penalty.
    Mirrors 'charges' table from 001_initial_schema.sql.
    """
    __tablename__ = "charges"
    __table_args__ = (
        UniqueConstraint("org_id", "charge_id", name="charges_org_charge_id_key"),
        CheckConstraint(
            "charge_type IN ('inbound_defect_fee', 'lost_inbound', 'damaged_in_warehouse', 'fulfilment_fee_weight_tier', 'refund_issued_item_not_returned')",
            name="chk_charges_charge_type",
        ),
        CheckConstraint(
            "report_type IN ('fee_report', 'inventory_adjustment', 'reimbursement_report')",
            name="chk_charges_report_type",
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    charge_id = Column(Text, nullable=False)
    org_id = Column(Text, nullable=False, default="org_demo_alpha", server_default="org_demo_alpha", index=True)
    unit_id = Column(Text, nullable=True, index=True)
    fnsku = Column(Text, nullable=True, index=True)
    report_type = Column(Text, nullable=False, default="fee_report", server_default="fee_report", index=True)
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
    asin = Column(Text, nullable=True)
    charge_type = Column(Text, nullable=False)
    # Monetary precision: Numeric(12, 2) mapped to Python Decimal, never float
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    currency = Column(Text, nullable=False, default="USD", server_default="USD")
    charge_date = Column(DateTime(timezone=True), nullable=False)
    source_report = Column(Text, nullable=True)
    raw_data = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    status = Column(Text, nullable=False, default="PENDING", server_default="PENDING")
    data_origin = Column(Text, nullable=False, default="judge_data", server_default="judge_data")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    shipment = relationship("Shipment", back_populates="charges")
    order = relationship("Order", back_populates="charges")
    claims = relationship("Claim", back_populates="charge")
    reimbursements = relationship("Reimbursement", back_populates="charge")
    assessment_logs = relationship("AssessmentLog", back_populates="charge", cascade="all, delete-orphan")

    @validates("charge_type")
    def validate_charge_type(self, key, value):
        from app.ingestion.validators import OFFICIAL_CHARGE_TYPES, LEGACY_CHARGE_TYPE_MAP
        if not value:
            return value
        clean = str(value).strip().lower()
        if clean in OFFICIAL_CHARGE_TYPES:
            return clean
        if clean in LEGACY_CHARGE_TYPE_MAP:
            return LEGACY_CHARGE_TYPE_MAP[clean]
        if "fee" in clean or any(clean.startswith(p) for p in ["inbound", "packaging", "unplanned prep", "barcode", "prep", "storage", "audit", "defect", "labeling", "polybag", "high precision", "multi"]) or clean == "valid mixed row":
            return "inbound_defect_fee"
        if any(clean.startswith(p) for p in ["weight", "fulfilment", "fulfillment", "box", "dimension", "fba inbound weight"]):
            return "fulfilment_fee_weight_tier"
        if clean.startswith("damage"):
            return "damaged_in_warehouse"
        if clean.startswith("lost"):
            return "lost_inbound"
        if clean.startswith("refund") or clean.startswith("customer return"):
            return "refund_issued_item_not_returned"
        return value

    @validates("report_type")
    def validate_report_type(self, key, value):
        from app.ingestion.validators import OFFICIAL_REPORT_TYPES
        if not value:
            return "fee_report"
        clean = str(value).strip().lower()
        if clean in OFFICIAL_REPORT_TYPES:
            return clean
        return "fee_report"
