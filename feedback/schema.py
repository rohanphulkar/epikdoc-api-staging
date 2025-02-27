from pydantic import BaseModel
from typing import Optional

class FeedbackSchema(BaseModel):
    feedback: str
    rating: int
    suggestions: Optional[str] = None

    class Config:
        from_attributes = True
