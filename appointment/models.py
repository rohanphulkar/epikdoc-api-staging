import enum
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from db.db import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class AppointmentStatus(enum.Enum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    patient_number: Mapped[str] = mapped_column(String(50), nullable=True)
    patient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False) 
    doctor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str] = mapped_column(String(1000), nullable=True)
    appointment_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    checked_out_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(SQLAlchemyEnum(AppointmentStatus), nullable=False)
    share_on_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    share_on_sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    share_on_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)