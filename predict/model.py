from sqlalchemy import String, DateTime, ForeignKey, Float, Boolean, Text, JSON
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from db.db import Base
from datetime import datetime
import uuid
from typing import Optional

def generate_uuid():
    return str(uuid.uuid4())


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    patient: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    original_image: Mapped[str] = mapped_column(String(500), nullable=False)  # Image path should not be null
    is_annotated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    xray_id: Mapped[str] = mapped_column(String(36), nullable=False)
    predicted_image: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Can be null initially
    prediction: Mapped[str] = mapped_column(LONGTEXT, nullable=False)  # Changed to LONGTEXT to handle very large strings
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String(36), ForeignKey("predictions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    include: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    color_hex: Mapped[str] = mapped_column(String(255), nullable=False, default='#FFFFFF')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class DeletedLabel(Base):
    __tablename__ = "deleted_labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    label_id: Mapped[str] = mapped_column(String(36), ForeignKey("labels.id"), nullable=False)
    prediction_data: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)