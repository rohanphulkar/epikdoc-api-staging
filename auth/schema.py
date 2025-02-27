from pydantic import BaseModel
from typing import Optional

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


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    phone: str

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

