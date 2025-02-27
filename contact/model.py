from db.db import Base
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
import uuid
from datetime import datetime

def generate_uuid():
    return str(uuid.uuid4())

class ContactUs(Base):
    __tablename__ = "contact_us"
    
    id: Mapped[str] = mapped_column(String(36), nullable=True, unique=True, default=generate_uuid, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_size: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)