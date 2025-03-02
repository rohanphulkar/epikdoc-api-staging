from pydantic import BaseModel
from typing import List, Optional

class UserCreateWithPermissions(BaseModel):
    name: str
    email: str
    password: str
    phone: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None
    user_type: str = "doctor"
    permissions: List[str]

class UserUpdateSchema(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None
    user_type: Optional[str] = None
    permissions: Optional[List[str]] = None
