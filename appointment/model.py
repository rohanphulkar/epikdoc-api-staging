
import enum
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Boolean, Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from db.db import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())


class AppointmentStatus(enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    purpose_of_visit: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(SQLAlchemyEnum(AppointmentStatus), nullable=False)
    share_on_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    share_on_sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    share_on_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)