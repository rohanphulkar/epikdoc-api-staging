from sqlalchemy import String, DateTime, ForeignKey, Float, Boolean, Text, JSON, Enum as SQLAlchemyEnum
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from db.db import Base
from datetime import datetime
import uuid
from typing import Optional
import enum

def generate_uuid() -> str:
    """Generate a unique UUID string"""
    return str(uuid.uuid4())

class TicketStatus(enum.Enum):
    """Enum representing possible support ticket statuses"""
    OPEN = "open"
    PENDING = "pending" 
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

class TicketPriority(enum.Enum):
    """Enum representing support ticket priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class Chat(Base):
    """Model representing a chat conversation between a user and support"""
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class Message(Base):
    """Model representing individual messages in a chat conversation"""
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    chat: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), nullable=False)
    question: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    answer: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class SupportTicket(Base):
    """Model representing support tickets submitted by users"""
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    status: Mapped[TicketStatus] = mapped_column(SQLAlchemyEnum(TicketStatus), nullable=False, default=TicketStatus.OPEN)
    priority: Mapped[TicketPriority] = mapped_column(SQLAlchemyEnum(TicketPriority), nullable=False, default=TicketPriority.LOW)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
