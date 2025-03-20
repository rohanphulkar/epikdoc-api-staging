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
    treatment_date: datetime
    treatment_name: str
    tooth_number: Optional[str] = None
    treatment_notes: Optional[str] = None
    quantity: int = 1
    treatment_cost: float
    amount: float
    discount: Optional[float] = None
    discount_type: Optional[str] = None

    class Config:
        from_attributes = True

class TreatmentUpdate(BaseModel):
    treatment_date: Optional[datetime] = None
    treatment_name: Optional[str] = None
    tooth_number: Optional[str] = None
    treatment_notes: Optional[str] = None
    quantity: Optional[int] = None
    treatment_cost: Optional[float] = None
    amount: Optional[float] = None
    discount: Optional[float] = None
    discount_type: Optional[str] = None

    class Config:
        from_attributes = True


class TreatmentPlanItemBase(BaseModel):
    treatment_name: str
    unit_cost: float
    quantity: int = 1
    discount: Optional[float] = None
    discount_type: Optional[str] = None
    amount: float
    treatment_description: Optional[str] = None
    tooth_diagram: Optional[str] = None

class TreatmentPlanCreate(BaseModel):
    patient_id: Optional[str] = None
    appointment_id: Optional[str] = None
    date: datetime
    treatment_plan_items: List[TreatmentPlanItemBase]

    class Config:
        from_attributes = True

class TreatmentPlanUpdate(BaseModel):
    date: Optional[datetime] = None
    treatment_plan_items: Optional[List[TreatmentPlanItemBase]] = None

    class Config:
        from_attributes = True

