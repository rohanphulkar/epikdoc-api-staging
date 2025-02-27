from sqlalchemy import String, Integer, DateTime, Float, Enum as SQLAlchemyEnum, ForeignKey, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from db.db import Base
import uuid
import enum
from pydantic import validator

def generate_uuid():
    return str(uuid.uuid4())

class PaymentStatus(enum.Enum):
    PENDING = "pending"
    PAID = "paid" 
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"

class CouponType(enum.Enum):
    PERCENTAGE = "percentage"
    AMOUNT = "amount"

class SubscriptionStatus(enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    CANCELLED = "cancelled"

class CouponUsers(Base):
    __tablename__ = "coupon_users"
    
    coupon_id: Mapped[str] = mapped_column(String(36), ForeignKey("coupons.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)

class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    code: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    type: Mapped[CouponType] = mapped_column(SQLAlchemyEnum(CouponType), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, default=None)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    used_by_users = relationship("User", secondary="coupon_users")

    @validator('code', pre=True, always=True)
    def validate_code(cls, v):
        if ' ' in v or not v.isalnum():
            raise ValueError('Code cannot contain spaces and special characters')
        return v.upper()

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    plan: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    billing_frequency: Mapped[str] = mapped_column(String(255), nullable=False, default="monthly")
    coupon: Mapped[str | None] = mapped_column(String(36), ForeignKey("coupons.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    final_amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(SQLAlchemyEnum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    subscription_id: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(SQLAlchemyEnum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.PENDING)
    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class CancellationStatus(enum.Enum):
    PENDING = "pending"
    CANCELLED = "cancelled"
    FAILED = "failed"

class CancellationRequest(Base):
    __tablename__ = "cancellation_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    subscription: Mapped[str] = mapped_column(String(36), ForeignKey("subscriptions.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    feedback: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    status: Mapped[CancellationStatus] = mapped_column(SQLAlchemyEnum(CancellationStatus), nullable=False, default=CancellationStatus.PENDING)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class InvoiceStatus(enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"

class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(255), nullable=False)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(SQLAlchemyEnum(InvoiceStatus), nullable=False, default=InvoiceStatus.PENDING)
    file_path: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
