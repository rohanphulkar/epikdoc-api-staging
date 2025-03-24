from sqlalchemy import String, DateTime, ForeignKey, Float, Boolean, Text, JSON
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from db.db import Base
from datetime import datetime
import uuid
from typing import Optional

def generate_uuid():
    return str(uuid.uuid4())

class XRay(Base):
    __tablename__ = "xrays"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String(36), ForeignKey("predictions.id"), nullable=True)
    patient: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    clinic: Mapped[str] = mapped_column(String(36), ForeignKey("clinics.id"), nullable=False)
    original_image: Mapped[str] = mapped_column(String(500), nullable=False)
    predicted_image: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_annotated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_opg: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    xray_id: Mapped[str] = mapped_column(String(36), ForeignKey("xrays.id"), nullable=False)
    prediction: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class Legend(Base):
    __tablename__ = "legends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String(36), ForeignKey("predictions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    include: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    color_hex: Mapped[str] = mapped_column(String(255), nullable=False, default='#FFFFFF')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class DeletedLegend(Base):
    __tablename__ = "deleted_legends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    legend_id: Mapped[str] = mapped_column(String(36), ForeignKey("legends.id"), nullable=False)
    prediction_data: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
