from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index
from sqlalchemy import String, DateTime, Text, ForeignKey, Integer, Float, Boolean
from db.db import Base
from typing import Optional
from datetime import datetime
import uuid

def generate_uuid():
    return str(uuid.uuid4())


class TreatmentNameSuggestion(Base):
    __tablename__ = "treatment_name_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    treatment_name: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class ComplaintSuggestion(Base):
    __tablename__ = "complaint_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    complaint: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)



class DiagnosisSuggestion(Base):
    __tablename__ = "diagnosis_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    diagnosis: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)



class VitalSignSuggestion(Base):
    __tablename__ = "vital_sign_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    vital_sign: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

