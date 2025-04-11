from sqlalchemy import Float, String, DateTime, ForeignKey, Enum as SQLAlchemyEnum, Integer, Boolean, null, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.db import Base
from datetime import datetime
import uuid
import enum
from typing import Optional, List

def generate_uuid():
    return str(uuid.uuid4())

class Gender(enum.Enum):
    MALE = "male"
    FEMALE = "female" 
    OTHER = "other"

class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete='CASCADE'), nullable=True)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
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
    abha_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    age: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    anniversary_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    blood_group: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    occupation: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    relationship: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    medical_history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allergies: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    habits: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    height: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    referred_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    groups: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    patient_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id", ondelete='CASCADE'), nullable=False)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("appointments.id", ondelete='CASCADE'), nullable=True)
    clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
    doctor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete='CASCADE'), nullable=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    attachments: Mapped[List["ClinicalNoteAttachment"]] = relationship("ClinicalNoteAttachment", back_populates="clinical_note")
    treatments: Mapped[List["ClinicalNoteTreatment"]] = relationship("ClinicalNoteTreatment", back_populates="clinical_note")
    medicines: Mapped[List["Medicine"]] = relationship("Medicine", back_populates="clinical_note")
    complaints: Mapped[List["Complaint"]] = relationship("Complaint", back_populates="clinical_note")
    diagnoses: Mapped[List["Diagnosis"]] = relationship("Diagnosis", back_populates="clinical_note")
    vital_signs: Mapped[List["VitalSign"]] = relationship("VitalSign", back_populates="clinical_note")
    notes: Mapped[List["Notes"]] = relationship("Notes", back_populates="clinical_note")
    observations: Mapped[List["Observation"]] = relationship("Observation", back_populates="clinical_note")
    investigations: Mapped[List["Investigation"]] = relationship("Investigation", back_populates="clinical_note")


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="complaints")


class Diagnosis(Base):
    __tablename__ = "diagnoses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="diagnoses")


class VitalSign(Base):
    __tablename__ = "vital_signs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    vital_sign: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="vital_signs")

class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="observations")

class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    investigation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="investigations")


class Notes(Base):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="notes")


class ClinicalNoteAttachment(Base):
    __tablename__ = "clinical_note_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    attachment: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="attachments")



class ClinicalNoteTreatment(Base):
    __tablename__ = "clinical_note_treatments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="treatments")


class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    clinical_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_notes.id", ondelete='CASCADE'), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=True, default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    dosage: Mapped[str] = mapped_column(String(255), nullable=True)
    instructions: Mapped[str] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    clinical_note: Mapped["ClinicalNote"] = relationship("ClinicalNote", back_populates="medicines")


class PatientFile(Base):
    __tablename__ = "patient_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id", ondelete='CASCADE'), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
