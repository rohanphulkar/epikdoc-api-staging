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
    clinical_notes: Mapped[list["ClinicalNote"]] = relationship("ClinicalNote", back_populates="patient")

    __mapper_args__ = {"order_by": created_at.desc()}


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    patient: Mapped["Patient"] = relationship("Patient", back_populates="clinical_notes")
    attachments: Mapped[list["ClinicalNoteAttachment"]] = relationship("ClinicalNoteAttachment", back_populates="clinical_notes")
    treatments: Mapped[list["ClinicalNoteTreatment"]] = relationship("ClinicalNoteTreatment", back_populates="clinical_notes")
    medicines: Mapped[list["Medicine"]] = relationship("Medicine", back_populates="clinical_notes")
    complaints: Mapped[list["Complaint"]] = relationship("Complaint", back_populates="clinical_notes")
    diagnoses: Mapped[list["Diagnosis"]] = relationship("Diagnosis", back_populates="clinical_notes")
    vital_signs: Mapped[list["VitalSign"]] = relationship("VitalSign", back_populates="clinical_notes")
    notes: Mapped[list["Notes"]] = relationship("Notes", back_populates="clinical_notes")

    __mapper_args__ = {"order_by": created_at.desc()}

class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id"), nullable=False)
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    clinical_notes: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="complaints")

    __mapper_args__ = {"order_by": created_at.desc()}

class Diagnosis(Base):
    __tablename__ = "diagnoses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id"), nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_notes: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="diagnoses")

    __mapper_args__ = {"order_by": created_at.desc()}

class VitalSign(Base):
    __tablename__ = "vital_signs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id"), nullable=False)
    vital_sign: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_notes: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="vital_signs")

    __mapper_args__ = {"order_by": created_at.desc()}

class Notes(Base):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_notes_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id"), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_notes: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="notes")

    __mapper_args__ = {"order_by": created_at.desc()}

class ClinicalNoteAttachment(Base):
    __tablename__ = "clinical_note_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_notes_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id"), nullable=False)
    attachment: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_notes: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="attachments")

    __mapper_args__ = {"order_by": created_at.desc()}


class ClinicalNoteTreatment(Base):
    __tablename__ = "clinical_note_treatments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_notes_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_notes: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="treatments")

    __mapper_args__ = {"order_by": created_at.desc()}

class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_notes_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=True, default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    dosage: Mapped[str] = mapped_column(String(255), nullable=True)
    instructions: Mapped[str] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_notes: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="medicines")

    __mapper_args__ = {"order_by": created_at.desc()}
