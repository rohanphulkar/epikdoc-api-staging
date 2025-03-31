from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from .models import Gender
from fastapi import UploadFile
class PatientCreateSchema(BaseModel):
    clinic_id: Optional[str] = None
    name: str
    mobile_number: Optional[str] = None
    contact_number: Optional[str] = None
    email: Optional[str] = None
    secondary_mobile: Optional[str] = None
    gender: Gender
    address: Optional[str] = None
    locality: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    national_id: Optional[str] = None
    abha_id: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    age: Optional[str] = None
    anniversary_date: Optional[datetime] = None
    blood_group: Optional[str] = None
    occupation: Optional[str] = None
    relationship: Optional[str] = None
    medical_history: Optional[str] = None
    referred_by: Optional[str] = None
    groups: Optional[str] = None
    patient_notes: Optional[str] = None

    class Config:
        from_attributes = True

class PatientUpdateSchema(BaseModel):
    clinic_id: Optional[str] = None
    patient_number: Optional[str] = None
    name: Optional[str] = None
    mobile_number: Optional[str] = None
    contact_number: Optional[str] = None
    email: Optional[str] = None
    secondary_mobile: Optional[str] = None
    gender: Optional[Gender] = None
    address: Optional[str] = None
    locality: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    national_id: Optional[str] = None
    abha_id: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    age: Optional[str] = None
    anniversary_date: Optional[datetime] = None
    blood_group: Optional[str] = None
    occupation: Optional[str] = None
    relationship: Optional[str] = None
    medical_history: Optional[str] = None
    referred_by: Optional[str] = None
    groups: Optional[str] = None
    patient_notes: Optional[str] = None

    class Config:
        from_attributes = True

class ClinicalNoteAttachmentSchema(BaseModel):
    files: List[UploadFile]

    class Config:
        from_attributes = True

class ClinicalNoteTreatmentSchema(BaseModel):
    name: str

    class Config:
        from_attributes = True

class MedicineSchema(BaseModel):
    item_name: str
    quantity: int = 1
    price: float = 0
    dosage: Optional[str] = None
    instructions: Optional[str] = None
    amount: float = 0

    class Config:
        from_attributes = True

class ClinicalNoteCreateSchema(BaseModel):
    date: Optional[datetime] = None
    complaints: Optional[List[str]] = []
    diagnoses: Optional[List[str]] = []
    vital_signs: Optional[List[str]] = []
    notes: Optional[List[str]] = []
    attachments: Optional[List[ClinicalNoteAttachmentSchema]] = []
    treatments: Optional[List[ClinicalNoteTreatmentSchema]] = []
    medicines: Optional[List[MedicineSchema]] = []

    class Config:
        from_attributes = True
