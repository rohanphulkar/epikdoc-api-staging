from sqlalchemy import Float, String, DateTime, ForeignKey, Enum as SQLAlchemyEnum, Integer, Boolean, null, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.db import Base
from datetime import datetime
import uuid
import enum
from typing import Optional

def generate_uuid():
    return str(uuid.uuid4())

class Gender(enum.Enum):
    MALE = "male"
    FEMALE = "female" 
    OTHER = "other"

class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    patient_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mobile_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    secondary_mobile: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gender: Mapped[Gender] = mapped_column(SQLAlchemyEnum(Gender), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    locality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pincode: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    national_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    age: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    anniversary_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    blood_group: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    medical_history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referred_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    groups: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    patient_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    medical_records: Mapped[list["MedicalRecord"]] = relationship("MedicalRecord", back_populates="patient")


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    vital_signs: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    patient: Mapped["Patient"] = relationship("Patient", back_populates="medical_records")
    attachments: Mapped[list["MedicalRecordAttachment"]] = relationship("MedicalRecordAttachment", back_populates="medical_record")
    treatments: Mapped[list["MedicalRecordTreatment"]] = relationship("MedicalRecordTreatment", back_populates="medical_record")
    medicines: Mapped[list["Medicine"]] = relationship("Medicine", back_populates="medical_record")

class MedicalRecordAttachment(Base):
    __tablename__ = "medical_record_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    medical_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("medical_records.id"), nullable=False)
    attachment: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    medical_record: Mapped["MedicalRecord"] = relationship("MedicalRecord", back_populates="attachments")


class MedicalRecordTreatment(Base):
    __tablename__ = "medical_record_treatments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    medical_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("medical_records.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    medical_record: Mapped["MedicalRecord"] = relationship("MedicalRecord", back_populates="treatments")

class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    medical_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("medical_records.id"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=True, default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    dosage: Mapped[str] = mapped_column(String(255), nullable=True)
    instructions: Mapped[str] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    medical_record: Mapped["MedicalRecord"] = relationship("MedicalRecord", back_populates="medicines")
