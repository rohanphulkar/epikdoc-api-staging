from sqlalchemy import String, DateTime, ForeignKey, Float, Boolean, Text, JSON, Integer, Enum as SQLAlchemyEnum
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.db import Base
from datetime import datetime
import uuid
import enum
from typing import Optional


def generate_uuid():
    return str(uuid.uuid4())

class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[Optional[str]] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=True)
    doctor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id"), nullable=True)
    date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expense_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vendor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)



class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[Optional[str]] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=True)
    date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id"), nullable=True)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("invoices.id"), nullable=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("appointments.id"), nullable=True)
    patient_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    patient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    receipt_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    treatment_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount_paid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_mode: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="pending")
    refund: Mapped[Optional[bool]] = mapped_column(Boolean, default=False, nullable=True)
    refund_receipt_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    refunded_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cancelled: Mapped[Optional[bool]] = mapped_column(Boolean, default=False, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)



class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[Optional[str]] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=True)
    date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id"), nullable=True)
    payment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("payments.id"), nullable=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("appointments.id"), nullable=True)
    patient_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    patient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doctor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cancelled: Mapped[Optional[bool]] = mapped_column(Boolean, default=False, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)
    invoice_items: Mapped[list["InvoiceItem"]] = relationship("InvoiceItem", back_populates="invoice")



class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    invoice_id: Mapped[str] = mapped_column(String(36), ForeignKey("invoices.id"), nullable=False)
    treatment_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    unit_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_level_tax_discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tax_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tax_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="invoice_items")
