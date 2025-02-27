from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum

class AppointmentStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

class DoctorDetails(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str]

    class Config:
        from_attributes = True

class PatientDetails(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    date_of_birth: datetime
    gender: str

    class Config:
        from_attributes = True

class AppointmentCreate(BaseModel):
    patient_id: str
    purpose_of_visit: str = Field(..., max_length=255)
    description: str = Field(..., max_length=255)
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus = AppointmentStatus.PENDING
    share_on_email: bool = False
    share_on_sms: bool = False
    share_on_whatsapp: bool = False

    class Config:
        from_attributes = True

class AppointmentUpdate(BaseModel):
    purpose_of_visit: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=255)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[AppointmentStatus] = None
    share_on_email: Optional[bool] = None
    share_on_sms: Optional[bool] = None
    share_on_whatsapp: Optional[bool] = None

    class Config:
        from_attributes = True

class AppointmentResponse(BaseModel):
    id: str
    purpose_of_visit: str
    description: str
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus
    share_on_email: bool
    share_on_sms: bool
    share_on_whatsapp: bool
    created_at: datetime
    updated_at: datetime
    doctor: DoctorDetails
    patient: PatientDetails

    class Config:
        from_attributes = True
