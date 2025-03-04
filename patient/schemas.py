from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from .models import Gender

class PatientCreateSchema(BaseModel):
    name: str
    mobile_number: str
    email: str
    date_of_birth: datetime
    gender: Gender

    class Config:
        from_attributes = True

class PatientUpdateSchema(BaseModel):
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
    date_of_birth: Optional[datetime] = None
    age: Optional[str] = None
    anniversary_date: Optional[datetime] = None
    blood_group: Optional[str] = None
    remarks: Optional[str] = None
    medical_history: Optional[str] = None
    referred_by: Optional[str] = None
    groups: Optional[str] = None
    patient_notes: Optional[str] = None

    class Config:
        from_attributes = True

class MedicalRecordTreatmentSchema(BaseModel):
    name: str

    class Config:
        from_attributes = True

class MedicineSchema(BaseModel):
    name: str
    quantity: int = 1
    price: float = 0
    dosage: Optional[str] = None
    instructions: Optional[str] = None

    class Config:
        from_attributes = True

class MedicalRecordCreateSchema(BaseModel):
    complaint: str
    diagnosis: str
    vital_signs: str
    treatments: Optional[List[MedicalRecordTreatmentSchema]] = []
    medicines: Optional[List[MedicineSchema]] = []

    class Config:
        from_attributes = True
