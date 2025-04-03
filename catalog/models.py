from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, Text, ForeignKey, Integer, Float, Boolean, Enum as SQLAlchemyEnum
from db.db import Base
from typing import Optional, List
from datetime import datetime
import uuid, enum
from appointment.models import Appointment
def generate_uuid():
    return str(uuid.uuid4())

class ProcedureCatalog(Base):
    __tablename__ = "procedure_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete='CASCADE'), nullable=False)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
    treatment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    treatment_cost: Mapped[str] = mapped_column(String(255), nullable=False, default="0")
    treatment_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(String(50), nullable=True, default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class TreatmentPlan(Base):
    __tablename__ = "treatment_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    appointment_id: Mapped[str] = mapped_column(String(40), ForeignKey('appointments.id', ondelete='CASCADE'), nullable=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id", ondelete='CASCADE'), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    doctor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete='CASCADE'), nullable=True)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    treatments: Mapped[List["Treatment"]] = relationship("Treatment", back_populates="treatment_plan")

class Treatment(Base):
    __tablename__ = "treatments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    appointment_id: Mapped[str] = mapped_column(String(40), ForeignKey('appointments.id', ondelete='CASCADE'), nullable=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id", ondelete='CASCADE'), nullable=True)
    treatment_plan_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("treatment_plans.id", ondelete='CASCADE'), nullable=True)
    doctor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete='CASCADE'), nullable=True)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
    treatment_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    treatment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tooth_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    treatment_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Percentage or Fixed
    treatment_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tooth_diagram: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    treatment_plan: Mapped["TreatmentPlan"] = relationship("TreatmentPlan", back_populates="treatments")


# class CompletedProcedure(Base):
#     __tablename__ = "completed_procedures"

#     id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
#     patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id", ondelete='CASCADE'), nullable=True)
#     appointment_id: Mapped[str] = mapped_column(String(40), ForeignKey('appointments.id', ondelete='CASCADE'), nullable=True)
#     doctor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete='CASCADE'), nullable=True)
#     clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
#     procedure_name: Mapped[str] = mapped_column(String(255), nullable=False)
#     unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
#     amount: Mapped[float] = mapped_column(Float, nullable=False)
#     procedure_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
#     updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
