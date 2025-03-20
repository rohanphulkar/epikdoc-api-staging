from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, Text, ForeignKey, Integer, Float, Boolean
from db.db import Base
from typing import Optional
from datetime import datetime
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class ProcedureCatalog(Base):
    __tablename__ = "procedure_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    treatment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    treatment_cost: Mapped[str] = mapped_column(String(255), nullable=False, default="0")
    treatment_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(String(50), nullable=True, default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __mapper_args__ = {"order_by": created_at.desc()}

class Treatment(Base):
    __tablename__ = "treatments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    appointment_id: Mapped[str] = mapped_column(String(40), ForeignKey('appointments.id'), nullable=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=True)
    treatment_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    treatment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tooth_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    treatment_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    treatment_cost: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Percentage or Fixed
    doctor: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    __mapper_args__ = {"order_by": created_at.desc()}



class TreatmentPlan(Base):
    __tablename__ = "treatment_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    appointment_id: Mapped[str] = mapped_column(String(40), ForeignKey('appointments.id'), nullable=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    doctor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    __mapper_args__ = {"order_by": created_at.desc()}

class TreatmentPlanItem(Base):
    __tablename__ = "treatment_plan_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    treatment_plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("treatment_plans.id"), nullable=False)
    treatment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Percentage or Fixed
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    treatment_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tooth_diagram: Mapped[Optional[str]] = mapped_column(Text, nullable=True)