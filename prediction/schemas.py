from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# Create Pydantic models for response serialization
class LabelResponse(BaseModel):
    id: str
    name: str
    percentage: float
    prediction_id: str
    include: bool
    color_hex: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class XRayResponse(BaseModel):
    id: str
    patient: str
    original_image: str
    predicted_image: Optional[str] = None
    is_annotated: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PredictionResponse(BaseModel):
    id: str
    xray_id: str
    prediction: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AddNotesRequest(BaseModel):
    notes: str

class LabelCreateAndUpdate(BaseModel):
    name: str
    color_hex: str


class NewImageAnnotation(BaseModel):
    x: float
    y: float
    width: float
    height: float
    formX: float
    formY: float
    id: int
    text: str
    color: str

    class Config:
        from_attributes = True
