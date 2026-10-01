from typing import List, Optional
from pydantic import BaseModel, Field


class FailedPendingChargeItem(BaseModel):
    id: str
    charge_id: str
    unit_id: Optional[str] = None
    fnsku: Optional[str] = None
    charge_type: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    stage: str
    error_reason: str
    status: str
    created_at: str


class FailedPendingChargesResponse(BaseModel):
    total: int
    items: List[FailedPendingChargeItem]
