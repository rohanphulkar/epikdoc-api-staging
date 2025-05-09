from sqlalchemy import String, DateTime, Boolean, Table, ForeignKey, Column, Float, Text, Enum as SQLAlchemyEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.db import Base
from datetime import datetime
import uuid
from typing import Optional, List
import enum

import random

def generate_unique_color():
    # Generate a random hex color code
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

# Association table for self-referential many-to-many relationship
doctors_created = Table(
    'doctors_created',
    Base.metadata,
    Column('creator_id', String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('doctor_id', String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
)

# Association table for user permissions
user_permissions = Table(
    'user_permissions',
    Base.metadata,
    Column('user_id', String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', String(36), ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

# Association table for doctors and clinics
doctor_clinics = Table(
    'doctor_clinics',
    Base.metadata,
    Column('doctor_id', String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('clinic_id', String(36), ForeignKey('clinics.id', ondelete='CASCADE'), primary_key=True)
)

def generate_uuid():
    return str(uuid.uuid4())    

class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, default=generate_uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), nullable=True, unique=True, default=generate_uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    profile_pic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    user_type: Mapped[str] = mapped_column(String(255), nullable=False, default="doctor")
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reset_token_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    otp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    otp_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    default_clinic_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
    color_code: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, default=generate_unique_color)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Self-referential many-to-many relationship
    created_doctors: Mapped[List["User"]] = relationship(
        "User",
        secondary=doctors_created,
        primaryjoin=(id == doctors_created.c.creator_id),
        secondaryjoin=(id == doctors_created.c.doctor_id),
        backref="created_by"
    )

    # Relationship with permissions
    permissions: Mapped[List[Permission]] = relationship(
        "Permission",
        secondary=user_permissions,
        backref="users"
    )

    # Relationship with clinics (for doctors)
    clinics: Mapped[List["Clinic"]] = relationship(
        "Clinic",
        secondary=doctor_clinics,
        back_populates="doctors"
    )

    # Default clinic relationship
    default_clinic: Mapped[Optional["Clinic"]] = relationship("Clinic", foreign_keys=[default_clinic_id])

    # Relationship with ImportLog
    import_logs: Mapped[List["ImportLog"]] = relationship("ImportLog", back_populates="user")

    def __repr__(self):
        return f"<User {self.email}>"


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, default=generate_uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    speciality: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(255), nullable=True)
    country: Mapped[str] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationship with doctors
    doctors: Mapped[List[User]] = relationship(
        "User",
        secondary=doctor_clinics,
        back_populates="clinics"
    )


class ImportStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class ImportLog(Base):
    __tablename__ = "import_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete='CASCADE'), nullable=False)
    clinic_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinics.id", ondelete='CASCADE'), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    zip_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[ImportStatus] = mapped_column(SQLAlchemyEnum(ImportStatus), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    current_stage: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    current_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    files_processed: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    total_files: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # Relationship with User
    user: Mapped["User"] = relationship("User", back_populates="import_logs")