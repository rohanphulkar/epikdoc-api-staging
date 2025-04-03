from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from db.db import Base
from datetime import datetime
import uuid

def generate_uuid():    
    return str(uuid.uuid4())

class Speciality(Base):
    __tablename__ = "specialities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class Country(Base):
    __tablename__ = "countries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
