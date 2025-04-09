from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class ProcedureCatalogCreate(BaseModel):
    treatment_name: str
    treatment_cost: str = "0"
    treatment_notes: Optional[str] = None
    locale: Optional[str] = "en"

    class Config:
        from_attributes = True

class ProcedureCatalogUpdate(BaseModel):
    treatment_name: Optional[str] = None
    treatment_cost: Optional[str] = None
    treatment_notes: Optional[str] = None
    locale: Optional[str] = None

    class Config:
        from_attributes = True

class TreatmentCreate(BaseModel):
    patient_id: Optional[str] = None
    appointment_id: Optional[str] = None
    treatment_plan_id: Optional[str] = None
    clinic_id: Optional[str] = None
    treatment_date: datetime
    treatment_name: str
    tooth_number: Optional[str] = None
    treatment_notes: Optional[str] = None
    quantity: int = 1
    unit_cost: float
    discount: Optional[float] = None
    discount_type: Optional[str] = None
    treatment_description: Optional[str] = None
    tooth_diagram: Optional[str] = None
    completed: Optional[bool] = False

    class Config:
        from_attributes = True

class TreatmentUpdate(BaseModel):
    treatment_date: Optional[datetime] = None
    treatment_name: Optional[str] = None
    tooth_number: Optional[str] = None
    treatment_notes: Optional[str] = None
    quantity: Optional[int] = None
    unit_cost: Optional[float] = None
    amount: Optional[float] = None
    discount: Optional[float] = None
    discount_type: Optional[str] = None
    treatment_description: Optional[str] = None
    tooth_diagram: Optional[str] = None
    completed: Optional[bool] = None

    class Config:
        from_attributes = True


class TreatmentPlanCreate(BaseModel):
    patient_id: Optional[str] = None
    appointment_id: Optional[str] = None
    date: datetime
    clinic_id: Optional[str] = None
    treatment_plan_items: List[TreatmentCreate]

    class Config:
        from_attributes = True

class TreatmentPlanUpdate(BaseModel):
    date: Optional[datetime] = None
    clinic_id: Optional[str] = None
    treatment_plan_items: Optional[List[TreatmentCreate]] = None

    class Config:
        from_attributes = True


class CompletedProcedureItemCreate(BaseModel):
    procedure_name: str
    unit_cost: float
    quantity: int = 1
    amount: Optional[float] = None
    discount: Optional[float] = None
    discount_type: Optional[str] = None
    procedure_description: Optional[str] = None

    class Config:
        from_attributes = True

class CompletedProcedureItemUpdate(BaseModel):
    id: Optional[str] = None
    procedure_name: Optional[str] = None
    unit_cost: Optional[float] = None
    quantity: Optional[int] = None
    amount: Optional[float] = None
    discount: Optional[float] = None
    discount_type: Optional[str] = None
    procedure_description: Optional[str] = None

    class Config:
        from_attributes = True


class CompletedProcedureCreate(BaseModel):
    clinic_id: Optional[str] = None
    appointment_id: Optional[str] = None
    completed_procedure_items: List[CompletedProcedureItemCreate]

    class Config:
        from_attributes = True

class CompletedProcedureUpdate(BaseModel):
    clinic_id: Optional[str] = None
    appointment_id: Optional[str] = None
    completed_procedure_items: Optional[List[CompletedProcedureItemUpdate]] = None

    class Config:
        from_attributes = True