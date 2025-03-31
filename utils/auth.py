import jwt
from datetime import datetime, timedelta
from decouple import config
import re
import bcrypt, uuid
from fastapi import HTTPException, Request
from typing import Dict, Optional
import random

JWT_SECRET = str(config('JWT_SECRET'))
JWT_ALGORITHM = str(config('JWT_ALGORITHM'))

def validate_email(email: str) -> bool:
    """Validate email format using regex pattern."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_phone(phone: str) -> bool:
    """Validate phone number format - allows optional country code followed by 10 digits."""
    return bool(re.match(r'^(?:\+[0-9]{1,4})?[0-9]{10}$', phone))

def validate_password(password: str) -> bool:
    """
    Validate password strength.
    Must contain:
    - At least 8 characters
    - One uppercase letter
    - One lowercase letter 
    - One number
    """
    if len(password) < 8:
        return False
    return bool(re.search(r'[A-Z]', password) and 
                re.search(r'[a-z]', password) and 
                re.search(r'[0-9]', password))

def signJWT(user_id: str) -> Dict[str, str]:
    """Generate JWT token with user ID and expiration."""
    payload = {
        "user_id": user_id,
        "exp": datetime.now() + timedelta(days=30)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"access_token": token}

def decodeJWT(token: str) -> Optional[Dict]:
    """Decode and validate JWT token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hashed version."""
    try:
        hashed_password = hashed_password.strip()
        plain_bytes = plain_password.encode('utf-8')
        hash_bytes = hashed_password.encode('utf-8') if isinstance(hashed_password, str) else hashed_password
        
        if not hash_bytes.startswith(b'$2b$') and not hash_bytes.startswith(b'$2a$'):
            return False
            
        return bcrypt.checkpw(plain_bytes, hash_bytes)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """Generate password hash using bcrypt."""
    try:
        salt = bcrypt.gensalt(12)
        password_bytes = password.encode('utf-8')
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Error hashing password: {str(e)}")

def generate_reset_token() -> str:
    """Generate unique reset token using UUID4."""
    return str(uuid.uuid4())

def verify_token(request: Request) -> Dict:
    """
    Verify and decode token from request headers.
    Raises HTTPException if token is invalid.
    """
    token = request.headers.get("Authorization") or request.headers.get("authorization")
    
    if not token or not token.startswith("Bearer "):
        raise HTTPException(
            status_code=401, 
            detail="Invalid or missing Authorization header"
        )
        
    try:
        token = token.split(" ")[1]
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

def generate_otp():
    return f"{random.randint(100000, 999999)}"