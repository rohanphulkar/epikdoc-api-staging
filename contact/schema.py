from pydantic import BaseModel
from typing import Optional
class ContactUsSchema(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    topic: Optional[str] = None
    company_name: Optional[str] = None
    company_size: Optional[str] = None
    query: Optional[str] = None