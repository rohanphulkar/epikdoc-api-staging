from fastapi import UploadFile
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from .models import AppointmentStatus

class AppointmentResponse(BaseModel):
    id: str
    patient_id: str
    patient_number: str
    patient_name: str
    doctor_id: str
    doctor_name: str
    notes: Optional[str]
    appointment_date: datetime
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    status: AppointmentStatus
    share_on_email: bool
    share_on_sms: bool
    share_on_whatsapp: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AppointmentCreate(BaseModel):
    patient_id: Optional[str] = None
    doctor_id: Optional[str] = None
    clinic_id: Optional[str] = None
    notes: Optional[str] = None
    appointment_date: datetime
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: str = "scheduled"
    share_on_email: bool = False
    share_on_sms: bool = False
    share_on_whatsapp: bool = False

    class Config:
        from_attributes = True

class AppointmentUpdate(BaseModel):
    notes: Optional[str] = None
    appointment_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    checked_in_at: Optional[datetime] = None
    checked_out_at: Optional[datetime] = None
    status: Optional[str] = None
    share_on_email: Optional[bool] = None
    share_on_sms: Optional[bool] = None
    share_on_whatsapp: Optional[bool] = None

    class Config:
        from_attributes = True

class AppointmentReminder(BaseModel):
    remind_time_before: int
    send_reminder: bool

    class Config:
        from_attributes = True
class AppointmentFileCreate(BaseModel):
    remark: Optional[str] = None


class AppointmentFile(BaseModel):
    id: str
    remark: Optional[str]
    file_path: str
    appointment_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AppointmentFileUpdate(BaseModel):
    remark: str

    class Config:
        from_attributes = True
