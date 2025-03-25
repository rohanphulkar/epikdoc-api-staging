from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from fastapi import UploadFile

class UserLoginSchema(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str | int] = None

class UserSchema(BaseModel):
    email: str
    password: str

class UserCreateSchema(UserSchema):
    name: str
    phone: str
    user_type: str = "doctor"

class UserProfileUpdateSchema(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[UploadFile] = None
class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    phone: str

class OtpLoginSchema(BaseModel):
    phone: str

class OtpSchema(BaseModel):
    otp: int = Field(ge=1000, le=9999)

class ResetPasswordSchema(BaseModel):
    password: str
    confirm_password: str

class ChangePasswordSchema(BaseModel):
    old_password: str
    new_password: str
    confirm_new_password: str

class ForgotPasswordSchema(BaseModel):
    email: str


class GoogleLoginSchema(BaseModel):
    token: str

class ProcedureCatalogSchema(BaseModel):
    treatment_name: str
    treatment_cost: str | float | int
    treatment_notes: Optional[str] = None
    locale: Optional[str] = "en"

class ProcedureCatalogResponse(ProcedureCatalogSchema):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProcedureCatalogUpdateSchema(ProcedureCatalogSchema):
    treatment_name: Optional[str] = None
    treatment_cost: Optional[str | float | int] = None
    treatment_notes: Optional[str] = None
    locale: Optional[str] = None

    
class ClinicCreateSchema(BaseModel):
    name: str
    speciality: str
    address: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None

class ClinicUpdateSchema(ClinicCreateSchema):
    name: Optional[str] = None
    speciality: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None