from sqlalchemy import Float, String, DateTime, ForeignKey, Enum as SQLAlchemyEnum, Integer, Boolean, null
from sqlalchemy.orm import Mapped, mapped_column
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
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    gender: Mapped[Gender] = mapped_column(SQLAlchemyEnum(Gender), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class PatientXray(Base):
    __tablename__ = "patient_xrays"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    prediction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    original_image: Mapped[str] = mapped_column(String(255), nullable=False)
    annotated_image: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_opg: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    complaints: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vital_signs: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class Treatment(Base):
    __tablename__ = "treatments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    medical_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("medical_records.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class Instraction(enum.Enum):
    BEFORE_MEAL = "before_meal"
    AFTER_MEAL = "after_meal"
    ON_EMPTY_STOMACH = "on_empty_stomach"
    AS_NEEDED = "as_needed"
    AS_DIRECTED_BY_DOCTOR = "as_directed_by_doctor"
    

class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    medical_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("medical_records.id"), nullable=False)
    item: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dosage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    instraction: Mapped[Instraction] = mapped_column(SQLAlchemyEnum(Instraction), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class MedicalRecordAttachment(Base):
    __tablename__ = "medical_record_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    medical_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("medical_records.id"), nullable=False)
    file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)