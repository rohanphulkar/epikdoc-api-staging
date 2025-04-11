from pydantic import BaseModel
from typing import Optional

class TreatmentNameSuggestionSchema(BaseModel):
    treatment_name: str

    class Config:
        from_attributes = True

class DiagnosisSuggestionSchema(BaseModel):
    diagnosis: str

    class Config:
        from_attributes = True

class ComplaintSuggestionSchema(BaseModel):
    complaint: str

    class Config:
        from_attributes = True

class VitalSignSuggestionSchema(BaseModel):
    vital_sign: str

    class Config:
        from_attributes = True

class NotesSuggestionSchema(BaseModel):
    note: str

    class Config:
        from_attributes = True

class ObservationSuggestionSchema(BaseModel):
    observation: str

    class Config:
        from_attributes = True

class InvestigationSuggestionSchema(BaseModel):
    investigation: str

    class Config:
        from_attributes = True
