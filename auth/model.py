from sqlalchemy import String, Integer, DateTime, Boolean
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column
from db.db import Base
from datetime import datetime, timedelta
import uuid
from typing import Optional

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), nullable=True, unique=True, default=generate_uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    profile_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_verified: Mapped[int] = mapped_column(TINYINT(1), default=0)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    user_type: Mapped[str] = mapped_column(String(255), nullable=False, default="doctor")
    account_type: Mapped[str] = mapped_column(String(255), nullable=False, default="free_trial")
    billing_frequency: Mapped[str] = mapped_column(String(255), nullable=False, default="monthly")
    credits: Mapped[int] = mapped_column(Integer, default=3)
    credit_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now() + timedelta(days=7))
    is_annual: Mapped[int] = mapped_column(TINYINT(1), default=0)
    last_credit_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    otp: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    otp_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reset_token_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    data_sharing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # Whether TFA is enabled
    tfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Whether TFA is enabled
    tfa_otp: Mapped[Optional[str]] = mapped_column(String(6), nullable=True)  # OTP for TFA
    tfa_otp_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    email_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    push_notification: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    newsletter: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    has_subscription: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_credits: Mapped[int] = mapped_column(Integer, default=3)
    used_credits: Mapped[int] = mapped_column(Integer, default=0)
    payment_link: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<User {self.email}>"
