from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from .models import CouponType

class CouponSchema(BaseModel):
    code: str
    type: CouponType
    value: float
    max_uses: Optional[int] = None
    used_count: int = 0
    valid_from: datetime
    valid_until: Optional[datetime] = None
    is_active: bool = True

    class Config:
        from_attributes = True

class PaymentCreateSchema(BaseModel):
    plan: str
    coupon: Optional[str] = None
    plan_type: str = "monthly"

class PaymentVerifySchema(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str

class SubscriptionSchema(BaseModel):
    plan: str
    coupon: Optional[str] = None
    plan_type: str = "monthly"

class SubscriptionVerifySchema(BaseModel):
    razorpay_payment_id:str
    razorpay_subscription_id:str
    razorpay_signature:str

class PlanRenewSchema(BaseModel):
    coupon: Optional[str] = None

class CancellationRequestSchema(BaseModel):
    reason: str
    feedback: Optional[str] = None

class PaymentLinkSchema(BaseModel):
    name: str
    email: str
    phone: str
    plan: str = "starter"
    billing_frequency: str = "monthly"
    
