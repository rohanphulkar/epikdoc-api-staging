from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class SpecialityBase(BaseModel):
    name: str

class SpecialityCreate(SpecialityBase):
    pass

class SpecialityUpdate(SpecialityBase):
    pass

class Speciality(SpecialityBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CountryBase(BaseModel):
    name: str

class CountryCreate(CountryBase):
    pass

class CountryUpdate(CountryBase):
    pass

class Country(CountryBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
