from fastapi import APIRouter, Depends, Request, File, UploadFile, BackgroundTasks, Query
from db.db import get_db
from sqlalchemy.orm import Session
from .models import User, ImportLog, ImportStatus, Clinic
from .schemas import *
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from utils.auth import (
    validate_email, validate_phone, validate_password, signJWT, decodeJWT,
    verify_password, get_password_hash, generate_reset_token, verify_token
)
from utils.email import send_forgot_password_email
from utils.send_otp import send_otp, send_otp_email
from gauthuserinfo import get_user_info
import zipfile
import os
import pandas as pd
from appointment.models import *
from patient.models import *
from payment.models import *
from prediction.models import *
from catalog.models import *
from typing import List
import json, shutil
from math import ceil
from sqlalchemy import func
from collections import defaultdict
from suggestion.models import *
import random


user_router = APIRouter()

@user_router.post("/register", 
    response_model=dict,
    status_code=201,
    summary="Register a new user",
    description="""
    Create a new user account.
    
    Required fields:
    - email: Valid email address (e.g. user@example.com)
    - password: Strong password that meets security requirements
    - name: User's full name
    - phone: Valid phone number with country code (e.g. +1234567890)
    - user_type: Type of user account ("doctor" or "admin")
    
    Password requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    
    On successful registration:
    - Creates user account
    - Creates default clinic for user
    - Associates clinic with user
    """,
    responses={
        201: {
            "description": "User created successfully",
            "content": {
                "application/json": {
                    "example": {"message": "User created successfully"}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_fields": {
                            "value": {"error": "All fields are required"}
                        },
                        "invalid_email": {
                            "value": {"error": "Invalid email format"}
                        },
                        "invalid_phone": {
                            "value": {"error": "Invalid phone number"}
                        },
                        "invalid_password": {
                            "value": {"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"}
                        },
                        "email_exists": {
                            "value": {"error": "User already exists with this email"}
                        },
                        "phone_exists": {
                            "value": {"error": "User already exists with this phone number"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def register(user: UserCreateSchema, db: Session = Depends(get_db)):
    try:
        # Validate required fields
        if not user.email or not user.password or not user.name or not user.phone:
            return JSONResponse(status_code=400, content={"error": "All fields are required"})

        # Validate input formats
        if not validate_email(user.email):
            return JSONResponse(status_code=400, content={"error": "Invalid email format"})
        
        if not validate_phone(user.phone):
            return JSONResponse(status_code=400, content={"error": "Invalid phone number"})
            
        if not validate_password(user.password):
            return JSONResponse(status_code=400, content={"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"})
        
        # Check for existing users
        if db.query(User).filter(User.email == user.email).first():
            return JSONResponse(status_code=400, content={"error": "User already exists with this email"})

        if db.query(User).filter(User.phone == user.phone).first():
            return JSONResponse(status_code=400, content={"error": "User already exists with this phone number"})
        
        # Create new user
        new_user = User(
            email=user.email,
            password=get_password_hash(user.password),
            name=user.name,
            phone=user.phone,
            user_type=user.user_type,
            is_active=True,
            is_superuser=(user.user_type == "admin")
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        # Create default clinic for the user
        default_clinic = Clinic(
            name=f"{new_user.name}'s Clinic",
            speciality="General",
            email=new_user.email,
            phone=new_user.phone,
            address="",
            city="",
            country=""
        )
        db.add(default_clinic)
        db.commit()
        db.refresh(default_clinic)

        # Associate clinic with user
        new_user.clinics.append(default_clinic)
        default_clinic.doctors.append(new_user)
        new_user.default_clinic_id = default_clinic.id
        db.commit()
        
        return JSONResponse(status_code=201, content={"message": "User created successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/login", 
    response_model=dict, 
    status_code=200, 
    summary="Login user",
    description="""
    Authenticate user and get access token.
    
    Login options:
    1. Email + Password:
       - email: Registered email address
       - password: Account password
    
    2. Phone Number:
       - phone: Registered phone number (will trigger OTP flow)
    
    On successful email login:
    - Updates last_login timestamp
    - Generates JWT access token
    - Returns token and success message
    
    On successful phone submission:
    - Sends OTP to the phone number
    - Returns message to verify OTP
    """,
    responses={
        200: {
            "description": "Login successful or OTP sent",
            "content": {
                "application/json": {
                    "examples": {
                        "email_login": {
                            "value": {
                                "access_token": "eyJhbGciOiJIUzI1NiIs...",
                                "token_type": "bearer",
                                "message": "Login successful"
                            }
                        },
                        "phone_login": {
                            "value": {
                                "message": "OTP sent to your phone number"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_credentials": {
                            "value": {"error": "Either email with password or phone number is required"}
                        },
                        "missing_password": {
                            "value": {"error": "Password is required when logging in with email"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_credentials": {
                            "value": {"error": "Invalid credentials"}
                        },
                        "account_inactive": {
                            "value": {"error": "Your account is deactivated or deleted. Please contact support."}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def login(user: UserLoginSchema, db: Session = Depends(get_db)):
    try:
        # Check if either email or phone is provided
        if not user.email and not user.phone:
            return JSONResponse(status_code=400, content={"error": "Either email with password or phone number is required"})
        
        # Phone login flow - trigger OTP
        if user.phone and not user.email:
            db_user = db.query(User).filter(User.phone == user.phone).first()
            if not db_user:
                return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
            
            if not db_user.is_active:
                return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})
            
            otp = random.randint(1000, 9999)
            setattr(db_user, 'otp', otp)
            setattr(db_user, 'otp_expiry', datetime.now() + timedelta(minutes=10))
            db.commit()
            db.refresh(db_user)
            
            sms_sent = send_otp(user.phone, str(otp))
            email_sent = send_otp_email(db_user.email, str(otp))
            
            if sms_sent or email_sent:
                return JSONResponse(status_code=200, content={"message": "OTP sent to your phone number"})
            else:
                return JSONResponse(status_code=500, content={"error": "Failed to send OTP via both SMS and email"})
        
        # Email login flow - require password
        if user.email:
            if not user.password:
                return JSONResponse(status_code=400, content={"error": "Password is required when logging in with email"})
                
            db_user = db.query(User).filter(User.email == user.email).first()
            
            if not db_user:
                return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
            
            if not db_user.is_active:
                return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})
        
            if not verify_password(user.password, str(db_user.password)):
                return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
            
            setattr(db_user, 'last_login', datetime.now())
            db.commit()
            db.refresh(db_user)
            
            jwt_token = signJWT(str(db_user.id))
            return JSONResponse(status_code=200, content={"access_token": jwt_token["access_token"], "token_type": "bearer", "message": "Login successful"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    

@user_router.post("/login/otp/resend",
    response_model=dict,
    status_code=200,
    summary="Resend OTP",
    description="""
    Resend OTP to user's registered phone number.
    
    Required fields:
    - phone: Registered phone number with country code
    
    Process:
    - Generates new 4-digit OTP
    - Sends new OTP via SMS
    - Resets 10-minute expiry timer
    """,
    responses={
        200: {
            "description": "OTP resent successfully",
            "content": {
                "application/json": {
                    "example": {"message": "OTP resent successfully"}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "example": {"error": "Phone number is required"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "examples": {
                        "sms_failed": {
                            "value": {"error": "Failed to resend OTP"}
                        },
                        "server_error": {
                            "value": {"error": "Internal server error"}
                        }
                    }
                }
            }
        }
    }
)
async def resend_otp(user: OtpLoginSchema, db: Session = Depends(get_db)):
    try:
        if not user.phone:
            return JSONResponse(status_code=400, content={"error": "Phone number is required"})
        
        db_user = db.query(User).filter(User.phone == user.phone).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        otp = random.randint(1000, 9999)
        setattr(db_user, 'otp', otp)
        setattr(db_user, 'otp_expiry', datetime.now() + timedelta(minutes=10))
        db.commit()
        db.refresh(db_user)
        
        if send_otp(user.phone, str(otp)):
            return JSONResponse(status_code=200, content={"message": "OTP resent successfully"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to resend OTP"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.post("/login/otp/verify",
    response_model=dict,
    status_code=200,
    summary="Verify OTP and login",
    description="""
    Verify OTP and generate access token for login.
    
    Required fields:
    - otp: 4-digit OTP received via SMS
    
    Process:
    - Validates OTP
    - Checks OTP expiry
    - Generates JWT access token on success
    - Clears OTP data after successful verification
    """,
    responses={
        200: {
            "description": "OTP verified and login successful",
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJhbGciOiJIUzI1NiIs...",
                        "token_type": "bearer",
                        "message": "Login successful"
                    }
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_otp": {
                            "value": {"error": "OTP is required"}
                        },
                        "invalid_otp": {
                            "value": {"error": "Invalid OTP"}
                        },
                        "expired_otp": {
                            "value": {"error": "OTP expired"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def login_otp_verify(user: OtpSchema, db: Session = Depends(get_db)):
    try:
        if not user.otp:
            return JSONResponse(status_code=400, content={"error": "OTP is required"})
        
        db_user = db.query(User).filter(User.otp == user.otp).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if db_user.otp_expiry and db_user.otp_expiry < datetime.now():
            return JSONResponse(status_code=400, content={"error": "OTP expired"})
        
        if db_user.otp != user.otp:
            return JSONResponse(status_code=400, content={"error": "Invalid OTP"})
        
        # Reset OTP and expiry after successful verification
        setattr(db_user, 'otp', None)
        setattr(db_user, 'otp_expiry', None)
        db.commit()
        db.refresh(db_user)
        
        jwt_token = signJWT(str(db_user.id))
        return JSONResponse(status_code=200, content={"access_token": jwt_token["access_token"], "token_type": "bearer", "message": "Login successful"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
        
@user_router.get("/profile", 
    response_model=UserResponse,
    status_code=200,
    summary="Get user profile",
    description="""
    Get authenticated user's profile and associated clinic information.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Returns:
    - User profile details including:
      - Basic info (name, email, phone, bio)
      - Profile picture URL if exists
      - Associated clinics with default clinic marked
      - Account timestamps
    """,
    responses={
        200: {
            "description": "Profile retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "name": "John Doe",
                        "email": "john@example.com", 
                        "phone": "+1234567890",
                        "bio": "Doctor specializing in pediatrics",
                        "profile_pic": "http://example.com/uploads/profile.jpg",
                        "clinics": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "name": "Clinic 1",
                                "speciality": "Pediatrics",
                                "address": "123 Main St",
                                "city": "Anytown",
                                "country": "USA",
                                "phone": "+1234567890",
                                "is_default": True
                            }
                        ],
                        "created_at": "2023-01-01T00:00:00",
                        "updated_at": "2023-01-01T00:00:00"
                    }
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def get_user(request: Request, db: Session = Depends(get_db)):   
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        user_data = {
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "bio": user.bio,
        }

        clinics = user.clinics
        clinics_data = []
        for clinic in clinics:
            is_default = False
            if clinic.id == user.default_clinic_id:
                is_default = True
            clinics_data.append({
                "id": str(clinic.id),
                "name": clinic.name,
                "speciality": clinic.speciality,
                "address": clinic.address,
                "city": clinic.city,
                "country": clinic.country,
                "phone": clinic.phone,
                "is_default": is_default
            })

        if user.profile_pic:
            profile_pic = f"{request.base_url}{user.profile_pic}"
            user_data["profile_pic"] = profile_pic
        else:
            user_data["profile_pic"] = None
        
        user_data["clinics"] = clinics_data
        user_data["created_at"] = user.created_at.isoformat()
        user_data["updated_at"] = user.updated_at.isoformat()


        return JSONResponse(status_code=200, content=user_data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/clinic/create",
    response_model=dict,
    status_code=200,
    summary="Create new clinic",
    description="""
    Create a new clinic and associate it with the authenticated user.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Required fields:
    - name: Clinic name
    - speciality: Medical speciality
    - address: Physical address
    - city: City location
    - country: Country location
    - phone: Contact number
    - email: Contact email
    
    Process:
    - Creates new clinic
    - Associates clinic with user
    - Sets as default clinic
    """,
    responses={
        200: {
            "description": "Clinic created successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Clinic created successfully"}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "example": {"error": "You are already associated with this clinic"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def create_clinic(request: Request, clinic: ClinicCreateSchema, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Check if user is already associated with a clinic with the same details
        existing_clinic = db.query(Clinic).filter(
            Clinic.name == clinic.name,
            Clinic.address == clinic.address,
            Clinic.city == clinic.city,
            Clinic.country == clinic.country,
            Clinic.doctors.any(User.id == user.id)
        ).first()
        
        if existing_clinic:
            return JSONResponse(
                status_code=400, 
                content={"error": "You are already associated with this clinic"}
            )
        
        new_clinic = Clinic(
            name=clinic.name,
            speciality=clinic.speciality,
            address=clinic.address,
            city=clinic.city,
            country=clinic.country,
            phone=clinic.phone,
            email=clinic.email
        )
        db.add(new_clinic)
        db.commit()
        db.refresh(new_clinic)
        
        # Add the relationship after clinic is created
        new_clinic.doctors.append(user)
        user.clinics.append(new_clinic)
        user.default_clinic_id = new_clinic.id
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Clinic created successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.get("/get-clinics",
    response_model=dict,
    status_code=200,
    summary="Get all clinics",
    description="""
    Get all clinics associated with the authenticated user.
    """
)
async def get_clinics(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        clinics = user.clinics
        clinics_data = []
        for clinic in clinics:
            clinics_data.append({
                "id": str(clinic.id),
                "name": clinic.name,
                "speciality": clinic.speciality,
                "address": clinic.address,
                "city": clinic.city,
                "country": clinic.country,
                "phone": clinic.phone,
                "email": clinic.email
            })

        return JSONResponse(status_code=200, content={"clinics": clinics_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.get("/set-default-clinic/{clinic_id}",
    response_model=dict,
    status_code=200,
    summary="Set default clinic",
    description="""
    Set a clinic as the default clinic for the authenticated user.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Path parameters:
    - clinic_id: UUID of clinic to set as default
    
    Process:
    - Verifies user is associated with clinic
    - Updates user's default clinic setting
    """,
    responses={
        200: {
            "description": "Default clinic set successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Default clinic set successfully"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "value": {"error": "User not found"}
                        },
                        "clinic_not_found": {
                            "value": {"error": "Clinic not found"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def set_default_clinic(request: Request, clinic_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        clinic = db.query(Clinic).filter(Clinic.id == clinic_id, Clinic.doctors.any(User.id == user.id)).first()
        if not clinic:
            return JSONResponse(status_code=404, content={"error": "Clinic not found"})
        
        user.default_clinic_id = clinic_id
        db.commit()
        db.refresh(user)
        
        return JSONResponse(status_code=200, content={"message": "Default clinic set successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.patch("/clinic/update/{clinic_id}",
    response_model=dict,
    status_code=200,
    summary="Update clinic details",
    description="""
    Update details of an existing clinic.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Path parameters:
    - clinic_id: UUID of clinic to update
    
    Request body:
    - name: New clinic name (optional)
    - speciality: New clinic speciality (optional) 
    - address: New clinic address (optional)
    - city: New clinic city (optional)
    - country: New clinic country (optional)
    - phone: New clinic phone number (optional)
    - email: New clinic email (optional)
    """,
    responses={
        200: {
            "description": "Clinic updated successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Clinic updated successfully"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "value": {"error": "User not found"}
                        },
                        "clinic_not_found": {
                            "value": {"error": "Clinic not found"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error", 
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def update_clinic(request: Request,clinic_id: str, clinic: ClinicUpdateSchema, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        existing_clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
        if not existing_clinic:
            return JSONResponse(status_code=404, content={"error": "Clinic not found"})
        
        if clinic.name:
            existing_clinic.name = clinic.name
        if clinic.speciality:
            existing_clinic.speciality = clinic.speciality
        if clinic.address:
            existing_clinic.address = clinic.address
        if clinic.city:
            existing_clinic.city = clinic.city
        if clinic.country:
            existing_clinic.country = clinic.country
        if clinic.phone:
            existing_clinic.phone = clinic.phone
        if clinic.email:
            existing_clinic.email = clinic.email
        
        db.commit()
        db.refresh(existing_clinic)
        
        return JSONResponse(status_code=200, content={"message": "Clinic updated successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.delete("/clinic/delete",
    response_model=dict,
    status_code=200,
    summary="Delete a clinic",
    description="""
    Permanently delete a clinic and its associated data.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Path parameters:
    - clinic_id: UUID of clinic to delete
    
    This will delete:
    - Clinic details
    - Clinic associations with doctors
    - Any other clinic-specific data
    """,
    responses={
        200: {
            "description": "Clinic deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Clinic deleted successfully"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "value": {"error": "User not found"}
                        },
                        "clinic_not_found": {
                            "value": {"error": "Clinic not found"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def delete_clinic(request: Request, clinic_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        clinic = db.query(Clinic).filter(Clinic.id == clinic_id, Clinic.doctors.any(User.id == user.id)).first()
        if not clinic:
            return JSONResponse(status_code=404, content={"error": "Clinic not found"})
        
        db.delete(clinic)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Clinic deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.get("/created-doctors",
    response_model=dict,
    status_code=200,
    summary="Get created doctors",
    description="""
    Get list of all doctors created by the authenticated admin user.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Returns array of doctor profiles containing:
    - id: Doctor's unique ID
    - name: Doctor's full name
    - email: Doctor's email address
    - phone: Doctor's phone number
    - user_type: User type (always "doctor")
    """,
    responses={
        200: {
            "description": "Doctors retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "doctors": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "name": "Dr. Jane Smith",
                                "email": "jane.smith@hospital.com",
                                "phone": "+1234567890",
                                "user_type": "doctor"
                            }
                        ]
                    }
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def get_created_doctors(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        created_doctors = user.created_doctors
        doctors_data = []
        for doctor in created_doctors:
            doctors_data.append({
                "id": str(doctor.id),
                "name": doctor.name,
                "email": doctor.email,
                "phone": doctor.phone,
                "user_type": doctor.user_type
            })

        return JSONResponse(status_code=200, content={"doctors": doctors_data[::-1]})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/forgot-password",
    response_model=dict,
    status_code=200,
    summary="Initiate password reset",
    description="""
    Send password reset link to user's email.
    
    Required fields:
    - email: Registered email address
    
    Process:
    1. Validates email exists in system
    2. Generates reset token (expires in 3 hours)
    3. Sends reset link to user's email
    4. User clicks link to access reset password page
    """,
    responses={
        200: {
            "description": "Reset email sent successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Password reset email sent"}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_email": {
                            "value": {"error": "Email is required"}
                        },
                        "invalid_email": {
                            "value": {"error": "Invalid email"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "examples": {
                        "email_failed": {
                            "value": {"error": "Failed to send email"}
                        },
                        "server_error": {
                            "value": {"error": "Internal server error"}
                        }
                    }
                }
            }
        }
    }
)
async def forgot_password(user: ForgotPasswordSchema, request: Request, db: Session = Depends(get_db)):
    try:
        if not user.email:
            return JSONResponse(status_code=400, content={"error": "Email is required"})
        if not validate_email(user.email):
            return JSONResponse(status_code=400, content={"error": "Invalid email"})
            
        db_user = db.query(User).filter(User.email == user.email).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
            
        reset_token = generate_reset_token()
        reset_link = f"{request.headers.get('origin') or request.base_url}user/reset-password?token={reset_token}"
        
        setattr(db_user, 'reset_token', reset_token)
        setattr(db_user, 'reset_token_expiry', datetime.now() + timedelta(hours=3))
        
        db.commit()
        db.refresh(db_user)
        
        if send_forgot_password_email(user.email, reset_link):
            return JSONResponse(status_code=200, content={"message": "Password reset email sent"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to send email"})
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.post("/reset-password",
    response_model=dict,
    status_code=200,
    summary="Reset password with token",
    description="""
    Reset user password using token from email.
    
    Required query parameter:
    - token: Valid reset token from email link
    
    Required fields:
    - password: New password meeting requirements
    - confirm_password: Must match new password
    
    Password requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    
    Process:
    1. Validates reset token exists and not expired
    2. Validates password requirements
    3. Updates user's password
    4. Clears reset token
    """,
    responses={
        200: {
            "description": "Password reset successful",
            "content": {
                "application/json": {
                    "example": {"message": "Password reset successfully"}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "expired_token": {
                            "value": {"error": "Reset token expired"}
                        },
                        "missing_passwords": {
                            "value": {"error": "Password and confirm password are required"}
                        },
                        "invalid_password": {
                            "value": {"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"}
                        },
                        "passwords_mismatch": {
                            "value": {"error": "Passwords do not match"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def reset_password(token: str, user: ResetPasswordSchema, db: Session = Depends(get_db)):
    try:
        db_user = db.query(User).filter(User.reset_token == token).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
            
        expiry = getattr(db_user, 'reset_token_expiry', None)
        if expiry and expiry < datetime.now():
            return JSONResponse(status_code=400, content={"error": "Reset token expired"})
        
        if not user.password or not user.confirm_password:
            return JSONResponse(status_code=400, content={"error": "Password and confirm password are required"})
        
        if not validate_password(user.password):
            return JSONResponse(status_code=400, content={"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"})

        if user.password != user.confirm_password:
            return JSONResponse(status_code=400, content={"error": "Passwords do not match"})
            
        hashed_password = get_password_hash(user.password)
        setattr(db_user, 'password', hashed_password)
        setattr(db_user, 'reset_token', None)
        setattr(db_user, 'reset_token_expiry', None)

        db.commit()
        db.refresh(db_user)
        return JSONResponse(status_code=200, content={"message": "Password reset successfully"})

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/change-password",
    response_model=dict,
    status_code=200,
    summary="Change password",
    description="""
    Change password for authenticated user.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Required fields:
    - old_password: Current password for verification
    - new_password: New password meeting requirements
    - confirm_new_password: Must match new password
    
    Password requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    
    Process:
    1. Verifies old password matches current password
    2. Validates new password requirements
    3. Updates user's password
    """,
    responses={
        200: {
            "description": "Password changed successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Password changed successfully"}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "incorrect_old_password": {
                            "value": {"error": "Incorrect old password"}
                        },
                        "invalid_new_password": {
                            "value": {"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"}
                        },
                        "passwords_mismatch": {
                            "value": {"error": "New passwords do not match"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def change_password(user: ChangePasswordSchema, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        
        db_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if user.old_password:
            if not verify_password(user.old_password, str(db_user.password)):
                return JSONResponse(status_code=400, content={"error": "Incorrect old password"})
            
        if not validate_password(user.new_password):
            return JSONResponse(status_code=400, content={"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"})
            
        if user.new_password != user.confirm_new_password:
            return JSONResponse(status_code=400, content={"error": "New passwords do not match"})
        
        setattr(db_user, 'password', get_password_hash(user.new_password))
        db.commit()
        db.refresh(db_user)
        return JSONResponse(status_code=200, content={"message": "Password changed successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.patch("/update-profile",
    response_model=dict,
    status_code=200,
    summary="Update user profile",
    description="""
    Update authenticated user's profile information.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Request can be sent in two formats:
    
    1. multipart/form-data:
       - json: JSON string with profile fields
         {
           "name": "John Doe",        # Optional
           "phone": "+1234567890",    # Optional
           "bio": "Doctor bio..."     # Optional
         }
       - image: Profile picture file (optional)
       
    2. application/json:
       - Same profile fields in request body
       
    Image requirements:
    - Format: JPG/PNG
    - Max size: 5MB
    - Stored in: uploads/profile_pictures/
    
    Only provided fields will be updated.
    """,
    responses={
        200: {
            "description": "Profile updated successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Profile updated successfully"}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid input format"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def update_profile(request: Request, image: UploadFile = File(None), db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        
        db_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        # Get form data and body separately
        form = await request.form()
        body = {}
        
        # Extract JSON data from form if present
        if 'json' in form:
            try:
                json_str = str(form['json'])
                body = json.loads(json_str)
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={"error": "Invalid JSON format in form data"})
        else:
            # Try to read raw JSON body
            try:
                raw_body = await request.body()
                if raw_body:
                    body = await request.json()
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={"error": "Invalid JSON format in request body"})

        # Get values from body dict with get() method
        name = body.get('name')
        phone = body.get('phone')
        bio = body.get('bio')

        # Validate phone number format if provided
        if phone:
            # Add phone validation logic here if needed
            # For example: check if it matches a specific format
            if not isinstance(phone, str) or len(phone) < 8:
                return JSONResponse(status_code=400, content={"error": "Invalid phone number format"})
            
            # Check if phone number is already taken by another user
            existing_user = db.query(User).filter(User.phone == phone, User.id != db_user.id).first()
            if existing_user:
                return JSONResponse(status_code=400, content={"error": "Phone number already registered"})

        # Update user fields if provided
        if name:
            if not isinstance(name, str) or len(name) < 2:
                return JSONResponse(status_code=400, content={"error": "Invalid name format"})
            setattr(db_user, 'name', name)
            
        if phone:
            setattr(db_user, 'phone', phone)
            
        if bio:
            if not isinstance(bio, str):
                return JSONResponse(status_code=400, content={"error": "Invalid bio format"})
            setattr(db_user, 'bio', bio)
        
        if image:
            # Validate image format
            allowed_types = ["image/jpeg", "image/png"]
            if image.content_type not in allowed_types:
                return JSONResponse(status_code=400, content={"error": "Only JPG and PNG images are allowed"})

            # Read file contents
            file_contents = await image.read()

            # Check file size (5MB limit)
            if len(file_contents) > 5 * 1024 * 1024:  # 5MB in bytes
                return JSONResponse(status_code=400, content={"error": "Image size must be less than 5MB"})

            # Create upload directory if it doesn't exist
            upload_dir = "uploads/profile_pictures"
            os.makedirs(upload_dir, exist_ok=True)
            
            # Generate unique filename
            file_extension = os.path.splitext(image.filename)[1]
            file_name = f"profile_{db_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{file_extension}"
            file_path = os.path.join(upload_dir, file_name)
            
            # Delete old profile picture if it exists
            if db_user.profile_pic and os.path.exists(db_user.profile_pic):
                os.remove(db_user.profile_pic)
            
            # Save new image
            with open(file_path, "wb") as f:
                f.write(file_contents)
                
            # Update user profile URL in database
            setattr(db_user, 'profile_pic', file_path)
            
        db.commit()
        db.refresh(db_user)
        return JSONResponse(status_code=200, content={"message": "Profile updated successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.delete("/delete-profile",
    response_model=dict,
    status_code=200,
    summary="Delete user profile",
    description="""
    Permanently delete authenticated user's profile and all associated data.
    
    **Authentication:**
    - Requires valid Bearer token in Authorization header
    
    **Warning:**
    This action cannot be undone. All user data including appointments, patients, payments and other records will be permanently deleted.
    
    **Response:**
    - 200: Profile successfully deleted
    - 404: User not found
    - 500: Server error
    """,
    responses={
        200: {
            "description": "Profile deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Profile deleted successfully"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error message"}
                }
            }
        }
    }
)
async def delete_profile(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        
        db_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
            
        db.delete(db_user)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Profile deleted successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/google-login",
    response_model=dict,
    status_code=200,
    summary="Login with Google",
    description="""
    Authenticate user using Google OAuth token.
    
    **Request body:**
    - token (str): Valid Google OAuth token
    
    **Notes:**
    - If user doesn't exist, a new account will be created using Google profile data
    - If account is deactivated, login will be rejected
    
    **Response:**
    - 200: Login successful, returns JWT access token
    - 401: Account deactivated
    - 500: Server error
    """,
    responses={
        200: {
            "description": "Login successful",
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJhbGciOiJIUzI1NiIs...",
                        "token_type": "bearer",
                        "message": "Google login successful"
                    }
                }
            }
        },
        401: {
            "description": "Account deactivated",
            "content": {
                "application/json": {
                    "example": {"error": "Your account is deactivated or deleted. Please contact support."}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error message"}
                }
            }
        }
    }
)
async def google_login(user: GoogleLoginSchema, db: Session = Depends(get_db)):
    try:
        user_info = get_user_info(user.token)
        email = user_info["data"]['email']
        name = user_info["data"]['name']
        user_exists = db.query(User).filter(User.email == email).first()
        if not user_exists:
            new_user = User(email=email, name=name, password=None, user_type="doctor")
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            db_user = new_user
        else:
            db_user = user_exists
            
        if not db_user.is_active:
            return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})
            
        jwt_token = signJWT(str(db_user.id))
        return JSONResponse(status_code=200, content={"access_token": jwt_token["access_token"], "token_type": "bearer", "message": "Google login successful"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.get("/check-token-validity",
    response_model=dict,
    status_code=200,
    summary="Validate JWT token",
    description="""
    Verify if the provided JWT token is valid and not expired.
    
    **Authentication:**
    - Requires Bearer token in Authorization header
    
    **Response:**
    - 200: Token is valid
    - 401: Token is invalid or missing
    """,
    responses={
        200: {
            "description": "Token is valid",
            "content": {
                "application/json": {
                    "example": {"message": "Token is valid"}
                }
            }
        },
        401: {
            "description": "Invalid or missing token",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid": {
                            "value": {"error": "Invalid token"}
                        },
                        "missing": {
                            "value": {"error": "Invalid or missing Authorization header"}
                        }
                    }
                }
            }
        }
    }
)
async def check_token_validity(request: Request):
    try:
        token = request.headers.get("Authorization", "authorization")
        if token.split(" ")[0] == "Bearer":
            token = token.split(" ")[1]
        if not token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing Authorization header"})
        
        decoded_token = decodeJWT(token)
        user_id = decoded_token.get("user_id") if decoded_token else None
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        return JSONResponse(status_code=200, content={"message": "Token is valid"})
    except Exception as e:
        return JSONResponse(status_code=401, content={"error": str(e)})
    
@user_router.get("/deactivate-account", 
    response_model=dict,
    status_code=200,
    summary="Deactivate user account",
    description="""
    Temporarily deactivate authenticated user's account.
    
    **Authentication:**
    - Requires valid Bearer token in Authorization header
    
    **Notes:**
    - Account can only be reactivated by an administrator
    - All data is preserved but user cannot login while deactivated
    
    **Response:**
    - 200: Account successfully deactivated
    - 401: Invalid or missing authentication
    - 404: User not found
    - 500: Server error
    """,
    responses={
        200: {
            "description": "Account deactivated successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Account deactivated successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error message"}
                }
            }
        }
    }
)
async def deactivate_account(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not current_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        current_user.is_active = False
        db.commit()
        db.refresh(current_user)
        return JSONResponse(status_code=200, content={"message": "Account deactivated successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

async def process_patient_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing patient data")
    
    # Pre-process gender mapping - fix the map function to handle pandas Series
    def gender_mapper(x):
        x_str = str(x).lower()
        return Gender.FEMALE if "f" in x_str or "female" in x_str else Gender.MALE
    
    gender_map = df["Gender"].str.lower().apply(gender_mapper)
    
    # Convert date columns once and handle NaT values
    dob_series = pd.to_datetime(df["Date of Birth"].astype(str), errors='coerce')
    anniversary_series = pd.to_datetime(df["Anniversary Date"].astype(str), errors='coerce')

    # Prepare bulk insert
    new_patients = []
    for idx, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", "")).strip("'")
            
            # Handle NaT values for dates by converting to None - use loc for proper indexing
            dob = None if pd.isna(dob_series.loc[idx]) else dob_series.loc[idx].to_pydatetime()
            anniversary = None if pd.isna(anniversary_series.loc[idx]) else anniversary_series.loc[idx].to_pydatetime()

            existing_patient = db.query(Patient).filter(Patient.patient_number == patient_number, Patient.doctor_id == user.id).first()
            if existing_patient:
                continue
                
            new_patient = Patient(
                doctor_id=user.id,
                patient_number=patient_number,
                name=str(row.get("Patient Name", "")).strip("'")[:255],
                mobile_number=str(row.get("Mobile Number", "")).strip("'")[:255],
                contact_number=str(row.get("Contact Number", ""))[:255],
                email=str(row.get("Email Address", "")).strip("'")[:255],
                secondary_mobile=str(row.get("Secondary Mobile", ""))[:255],
                gender=gender_mapper(row.get("Gender", "")),  # Use the mapper function directly
                address=str(row.get("Address", "")).strip("'")[:255],
                locality=str(row.get("Locality", ""))[:255],
                city=str(row.get("City", ""))[:255],
                pincode=str(row.get("Pincode", ""))[:255],
                national_id=str(row.get("National Id", ""))[:255],
                date_of_birth=dob,
                age=str(row.get("Age", ""))[:5],
                anniversary_date=anniversary,
                blood_group=str(row.get("Blood Group", ""))[:50],
                medical_history=str(row.get("Medical History", "")),
                referred_by=str(row.get("Referred By", ""))[:255],
                groups=str(row.get("Groups", ""))[:255],
                patient_notes=str(row.get("Patient Notes", ""))
            )
            
            new_patients.append(new_patient)
            
        except Exception as e:
            print(f"Error processing patient row {idx}: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing patient row {idx}: {str(e)}"})
    
    # Bulk insert all patients at once
    if new_patients:
        try:
            db.bulk_save_objects(new_patients)
            db.commit()
        except Exception as e:
            print(f"Error during bulk insert: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error during bulk insert: {str(e)}"})

async def process_appointment_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing appointment data")
    
    # Clean column names
    df.columns = df.columns.str.strip()
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).str.strip("'").unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }
    
    # Convert 'Date' to datetime if it's not already
    if 'Date' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['Date']):
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    
    # Group appointments by patient number and date
    appointments_dict = defaultdict(lambda: defaultdict(list))
    for _, row in df.iterrows():
        patient_number = str(row.get("Patient Number", "")).strip("'")
        date = row.get("Date")
        if pd.notna(date):
            date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)
            
            appointment_details = {
                "Patient Name": str(row.get("Patient Name", "")).strip("'")[:255],
                "Doctor": str(row.get("DoctorName", "")).strip("'")[:255],
                "Status": str(row.get("Status", "SCHEDULED")).upper(),
                "Checked In At": row.get("Checked In At") if pd.notna(row.get("Checked In At")) else None,
                "Checked Out At": row.get("Checked Out At") if pd.notna(row.get("Checked Out At")) else None,
                "Notes": str(row.get("Notes", ""))
            }
            appointments_dict[patient_number][date_str].append(appointment_details)
    
    # Create appointment objects
    appointments = []
    for patient_number, dates in appointments_dict.items():
        patient = patients.get(patient_number)
        if patient:
            for date_str, appts in dates.items():
                for appt in appts:
                    status_str = appt["Status"]
                    status = AppointmentStatus.SCHEDULED if status_str == "SCHEDULED" else AppointmentStatus.CANCELLED
                    
                    appointments.append(Appointment(
                        patient_id=patient.id,
                        patient_number=patient_number[:255],
                        patient_name=appt["Patient Name"],
                        doctor_id=user.id,
                        doctor_name=appt["Doctor"],
                        notes=appt["Notes"],
                        appointment_date=pd.to_datetime(date_str) if date_str else None,
                        checked_in_at=pd.to_datetime(appt["Checked In At"]) if appt["Checked In At"] else None,
                        checked_out_at=pd.to_datetime(appt["Checked Out At"]) if appt["Checked Out At"] else None,
                        status=status
                    ))
    
    try:
        if appointments:
            db.bulk_save_objects(appointments)
            db.commit()
    except Exception as e:
        print(f"Error during bulk insert: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during bulk insert: {str(e)}"})

async def process_treatment_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing treatment data")
    
    # Clean column names
    df.columns = df.columns.str.strip()
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).str.strip("'").unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }
    
    # Convert 'Date' to datetime if it's not already
    if 'Date' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['Date']):
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        
    # Group treatments by patient number and date
    treatment_dict = defaultdict(lambda: defaultdict(list))
    
    # Group by Patient Number and then by Date
    for _, row in df.iterrows():
        patient_number = str(row.get("Patient Number", "")).strip("'")
        date = row.get("Date")
        
        if pd.notna(date):
            date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)
            
            treatment_details = {
                "Patient Name": str(row.get("Patient Name", "")).strip("'")[:255],
                "Treatment Name": str(row.get("Treatment Name", "")).strip("'")[:255],
                "Tooth Number": str(row.get("Tooth Number", "")).strip("'")[:50] if pd.notna(row.get("Tooth Number")) else "Not Specified",
                "Treatment Notes": str(row.get("Treatment Notes", "")).strip("'") if pd.notna(row.get("Treatment Notes")) else "No Notes",
                "Quantity": int(float(str(row.get("Quantity", 0)).strip("'"))),
                "Treatment Cost": float(str(row.get("Treatment Cost", 0.0)).strip("'")),
                "Amount": float(str(row.get("Amount", 0.0)).strip("'")),
                "Discount": float(str(row.get("Discount", 0)).strip("'")),
                "DiscountType": str(row.get("DiscountType", "")).strip("'")[:50],
                "Doctor": str(row.get("Doctor", "")).strip("'")[:255]
            }
            treatment_dict[patient_number][date_str].append(treatment_details)

    # Create treatment objects
    treatments = []
    for patient_number, dates in treatment_dict.items():
        patient = patients.get(patient_number)
        if patient:
            for date_str, treatments_list in dates.items():
                # search appointment
                appointment = db.query(Appointment).filter(Appointment.patient_id == patient.id, Appointment.appointment_date == pd.to_datetime(date_str)).first()
                if appointment:
                    for treatment_detail in treatments_list:
                        treatment_name = treatment_detail["Treatment Name"]
                    treatments.append(Treatment(
                        patient_id=patient.id,
                        appointment_id=appointment.id,
                        treatment_date=pd.to_datetime(date_str) if date_str else None,
                        treatment_name=treatment_name,
                        tooth_number=treatment_detail["Tooth Number"],
                        treatment_notes=treatment_detail["Treatment Notes"],
                        quantity=treatment_detail["Quantity"],
                        unit_cost=treatment_detail["Treatment Cost"],
                        amount=treatment_detail["Amount"],
                        discount=treatment_detail["Discount"],
                        discount_type=treatment_detail["DiscountType"],
                        doctor=user.id
                    ))
                    
                    # Add treatment name to suggestions if it doesn't exist
                    if treatment_name:
                        existing_treatment_suggestion = db.query(TreatmentNameSuggestion).filter(
                            TreatmentNameSuggestion.treatment_name == treatment_name
                        ).first()
                        if not existing_treatment_suggestion:
                            treatment_suggestion = TreatmentNameSuggestion(
                                treatment_name=treatment_name,
                            )
                            db.add(treatment_suggestion)

    try:
        if treatments:
            db.bulk_save_objects(treatments)
            db.commit()
    except Exception as e:
        print(f"Error during bulk insert: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during bulk insert: {str(e)}"})

def normalize_string(s: str) -> str:
    return " ".join(s.split()).lower()

async def process_clinical_note_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing clinical note data")
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).str.strip("'").unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }

    # Clean column names and convert Date to date only (without time)
    df.columns = df.columns.str.strip()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    
    # Create a nested dictionary structure for patient records
    patient_records = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    
    # Group by Patient Number and Date
    for (patient_number, date), group in df.groupby(["Patient Number", "Date"]):
        for _, row in group.iterrows():
            entry = {
                "Patient Name": row["Patient Name"],
                "Doctor": row["Doctor"] if "Doctor" in row else user.name,
                "Description": row["Description"]
            }
            # Append entry to the respective type (Complaints, Observations, etc.)
            patient_records[patient_number][str(date)][row["Type"]].append(entry)
    
    try:
        clinical_notes_created = 0
        
        for patient_number, dates in patient_records.items():
            patient = patients.get(patient_number)
            if not patient:
                continue
                
            for date_str, types in dates.items():
                # Search for an appointment on this date for this patient
                appointment = db.query(Appointment).filter(
                    Appointment.patient_id == patient.id,
                    Appointment.appointment_date == pd.to_datetime(date_str)
                ).first()
                
                # Create clinical note and link to appointment if found
                clinical_note = ClinicalNote(
                    patient_id=patient.id,
                    date=pd.to_datetime(date_str),
                    appointment_id=appointment.id if appointment else None
                )
                db.add(clinical_note)
                db.commit()
                db.refresh(clinical_note)
                clinical_notes_created += 1
                
                # Process each type of clinical note entry
                for note_type, entries in types.items():
                    if note_type == "'complaints'" or note_type == "complaints":
                        complaints_db = []
                        complaint_suggestions = set()
                        
                        for entry in entries:
                            cleaned_complaint = entry["Description"].strip().strip("'").strip('"')
                            complaints_db.append(Complaint(
                                clinical_note_id=clinical_note.id,
                                complaint=cleaned_complaint
                            ))
                            
                            # Add to suggestions
                            normalized_complaint = normalize_string(cleaned_complaint)
                            complaint_suggestions.add(normalized_complaint)
                        
                        # Bulk save complaints
                        if complaints_db:
                            db.bulk_save_objects(complaints_db)
                            db.commit()
                            
                        # Add unique suggestions
                        for complaint in complaint_suggestions:
                            db.merge(ComplaintSuggestion(complaint=complaint))
                        db.commit()
                            
                    elif note_type == "'diagnoses'" or note_type == "diagnoses":
                        diagnoses_db = []
                        diagnoses_suggestions = set()
                        
                        for entry in entries:
                            cleaned_diagnosis = entry["Description"].strip().strip("'").strip('"')
                            diagnoses_db.append(Diagnosis(
                                clinical_note_id=clinical_note.id,
                                diagnosis=cleaned_diagnosis
                            ))
                            
                            normalized_diagnosis = normalize_string(cleaned_diagnosis)
                            diagnoses_suggestions.add(normalized_diagnosis)
                        
                        if diagnoses_db:
                            db.bulk_save_objects(diagnoses_db)
                            db.commit()
                            
                        for diagnosis in diagnoses_suggestions:
                            db.merge(DiagnosisSuggestion(diagnosis=diagnosis))
                        db.commit()
                            
                    elif note_type == "'observations'" or note_type == "observations":
                        vital_signs_db = []
                        vital_sign_suggestions = set()
                        
                        for entry in entries:
                            cleaned_vital_sign = entry["Description"].strip().strip("'").strip('"')
                            vital_signs_db.append(VitalSign(
                                clinical_note_id=clinical_note.id,
                                vital_sign=cleaned_vital_sign
                            ))
                            
                            normalized_vital_sign = normalize_string(cleaned_vital_sign)
                            vital_sign_suggestions.add(normalized_vital_sign)
                        
                        if vital_signs_db:
                            db.bulk_save_objects(vital_signs_db)
                            db.commit()
                            
                        for vital_sign in vital_sign_suggestions:
                            db.merge(VitalSignSuggestion(vital_sign=vital_sign))
                        db.commit()
                            
                    elif note_type == "'treatmentnotes'" or note_type == "treatmentnotes":
                        notes_db = []
                        
                        for entry in entries:
                            cleaned_note = entry["Description"].strip().strip("'").strip('"')
                            notes_db.append(Notes(
                                clinical_notes_id=clinical_note.id,
                                note=cleaned_note
                            ))
                        
                        if notes_db:
                            db.bulk_save_objects(notes_db)
                            db.commit()
        
        # Update import log status
        import_log.status = ImportStatus.COMPLETED
        db.commit()
        
        return JSONResponse(
            status_code=200, 
            content={"message": f"Clinical note data processed successfully. Created {clinical_notes_created} clinical notes."}
        )
        
    except Exception as e:
        print(f"Error during clinical notes processing: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during clinical notes processing: {str(e)}"})

async def process_treatment_plan_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing treatment plan data")
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).str.strip("'").unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }
    
    # Clean and prepare data
    df.columns = df.columns.str.strip()
    df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
    df["UnitCost"] = pd.to_numeric(df["UnitCost"].astype(str).str.strip("'"), errors="coerce").fillna(0)
    df["Quantity"] = pd.to_numeric(df["Quantity"].astype(str).str.strip("'"), errors="coerce").fillna(1)
    df["Discount"] = pd.to_numeric(df["Discount"].astype(str).str.strip("'"), errors="coerce").fillna(0)
    df["Amount"] = pd.to_numeric(df["Amount"].astype(str).str.strip("'"), errors="coerce").fillna(0)
    
    # Group by patient and date to create treatment plans
    for (patient_number, date), group in df.groupby(["Patient Number", "Date"]):
        try:
            patient_number = str(patient_number)
            patient = patients.get(patient_number)
            
            if not patient:
                continue
                
            treatment_date = date.to_pydatetime() if not pd.isna(date) else datetime.now()
            
            # Find if there's an appointment for this patient on this date
            appointment = db.query(Appointment).filter(
                Appointment.patient_id == patient.id,
                func.date(Appointment.appointment_date) == treatment_date.date()
            ).first()
            
            # Create treatment plan
            treatment_plan = TreatmentPlan(
                patient_id=patient.id,
                doctor_id=user.id,
                date=treatment_date,
                appointment_id=appointment.id if appointment else None,
                # clinic_id=user.default_clinic_id
            )
            db.add(treatment_plan)
            db.commit()
            db.refresh(treatment_plan)
            
            # Process each treatment in the group
            for _, row in group.iterrows():
                treatment_name = str(row.get("Treatment Name", "")).strip("'")
                
                # Calculate final amount based on discount type
                unit_cost = float(row.get("Treatment Cost", 0.0))
                quantity = int(row.get("Quantity", 1))
                discount = float(row.get("Discount", 0))
                discount_type = str(row.get("DiscountType", "")).strip("'")
                
                # Calculate amount with discount applied
                if discount_type.upper() == "PERCENT":
                    amount = unit_cost * quantity * (1 - discount / 100)
                else:
                    amount = float(row.get("Amount", 0.0))
                
                treatment = Treatment(
                    treatment_plan_id=treatment_plan.id,
                    patient_id=patient.id,
                    doctor_id=user.id,
                    # clinic_id=user.default_clinic_id,
                    appointment_id=appointment.id if appointment else None,
                    treatment_date=treatment_date,
                    treatment_name=treatment_name[:255],
                    unit_cost=unit_cost,
                    quantity=quantity,
                    discount=discount,
                    discount_type=discount_type[:50],
                    amount=amount,
                    treatment_description=str(row.get("Treatment Description", "")),
                    tooth_number=str(row.get("Tooth Number", "")),
                    tooth_diagram=str(row.get("Tooth Diagram", ""))
                )
                
                db.add(treatment)
                db.commit()
                
                # Add treatment name to suggestions if not exists
                existing_treatment_name_suggestion = db.query(TreatmentNameSuggestion).filter(
                    TreatmentNameSuggestion.treatment_name == treatment_name
                ).first()
                
                if not existing_treatment_name_suggestion and treatment_name:
                    db.add(TreatmentNameSuggestion(treatment_name=treatment_name))
                    db.commit()
                    
        except Exception as e:
            print(f"Error processing treatment plan row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing treatment plan row: {str(e)}"})

async def process_expense_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing expense data")
    
    # Pre-process data and handle type conversions in bulk
    df["Amount"] = df["Amount"].astype(str).str.strip("'").astype(float)
    df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
    df["Expense Type"] = df["Expense Type"].astype(str).str[:255]
    df["Description"] = df["Description"].astype(str)
    df["Vendor Name"] = df["Vendor Name"].astype(str).str[:255]

    expenses = []
    try:
        # Build list of expense objects
        for _, row in df.iterrows():
            expense = Expense(
                date=row["Date"] if pd.notna(row["Date"]) else None,
                doctor_id=user.id,
                expense_type=row["Expense Type"],
                description=row["Description"],
                amount=row["Amount"],
                vendor_name=row["Vendor Name"]
            )
            expenses.append(expense)

        # Bulk insert all expenses
        if expenses:
            db.bulk_save_objects(expenses)
            db.commit()
            
    except Exception as e:
        print(f"Error processing expenses: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error processing expenses: {str(e)}"})

async def process_payment_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing payment data")
    
    # Pre-process data and handle type conversions in bulk
    def safe_float_convert(value):
        try:
            # First strip any quotes and whitespace
            cleaned = str(value).strip().strip("'")
            # Handle empty string case
            if not cleaned:
                return 0.0
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0
    
    def clean_string(value):
        if pd.isna(value):
            return ""
        return str(value).strip("'")
    
    df = df.groupby(["Patient Number", "Date"]).sum().reset_index()
    
    # Clean and convert data types
    df["Amount Paid"] = df["Amount Paid"].apply(safe_float_convert)
    df["Refunded amount"] = df["Refunded amount"].apply(lambda x: safe_float_convert(x) if pd.notna(x) else 0.0)
    df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
    df["Patient Number"] = df["Patient Number"].apply(lambda x: clean_string(x))
    df["Patient Name"] = df["Patient Name"].apply(lambda x: clean_string(x))
    df["Receipt Number"] = df["Receipt Number"].apply(lambda x: clean_string(x))
    df["Treatment name"] = df["Treatment name"].apply(lambda x: clean_string(x))
    df["Invoice Number"] = df["Invoice Number"].apply(lambda x: clean_string(x))
    df["Payment Mode"] = df["Payment Mode"].apply(lambda x: clean_string(x))
    df["Cancelled"] = df["Cancelled"].apply(lambda x: True if clean_string(x) == "1" else False)
    
    # Get all unique patient numbers
    patient_numbers = df["Patient Number"].str.strip("'").unique()
    
    # Bulk fetch all patients in one query
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }
    
    payments = []
    try:
        # Build list of payment objects
        for _, row in df.iterrows():
            patient_number = str(row["Patient Number"]).strip("'")
            patient = patients.get(patient_number)
            
            # Only query for appointment if patient exists
            appointment = None
            if patient:
                appointment = db.query(Appointment).filter(
                    Appointment.patient_id == patient.id, 
                    Appointment.appointment_date == row["Date"]
                ).first()
            
            if patient:
                payment = Payment(
                    date=row["Date"] if pd.notna(row["Date"]) else None,
                    doctor_id=user.id,
                    # clinic_id=user.clinic_id,
                    patient_id=patient.id,
                    appointment_id=appointment.id if appointment else None,
                    patient_number=patient_number,
                    patient_name=str(row.get("Patient Name", "")).strip("'")[:255],
                    receipt_number=str(row.get("Receipt Number", ""))[:255],
                    treatment_name=str(row.get("Treatment name", "")).strip("'")[:255],
                    amount_paid=row["Amount Paid"],
                    invoice_number=str(row.get("Invoice Number", ""))[:255],
                    notes=str(row.get("Notes", "")),
                    payment_mode=str(row.get("Payment Mode", "")),
                    refund=bool(row.get("Refund", False)),
                    refund_receipt_number=str(row.get("Refund Receipt Number", ""))[:255],
                    refunded_amount=row["Refunded amount"],
                    cancelled=bool(row.get("Cancelled", False))
                )
                payments.append(payment)
        
        # Bulk insert all payments
        if payments:
            db.bulk_save_objects(payments)
            db.commit()
            
        return JSONResponse(status_code=200, content={"message": f"Successfully processed {len(payments)} payment records"})
    except Exception as e:
        print(f"Error processing payments: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error processing payments: {str(e)}"})

async def process_invoice_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing invoice data")
    
    # Get all unique patient numbers from the dataframe
    patient_numbers = df["Patient Number"].str.strip("'").unique()
    
    # Bulk fetch all patients in one query
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }

    df = df.groupby(["Patient Number", "Date"]).sum().reset_index()
    
    df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
    
    try:
        for _, row in df.iterrows():
            patient_number = str(row.get("Patient Number", ""))
            patient = patients.get(patient_number)
            appointment = None
            if patient:
                appointment = db.query(Appointment).filter(
                    Appointment.patient_id == patient.id,
                    Appointment.appointment_date == row["Date"]
                ).first()
                payment = None
                if appointment:
                    payment = db.query(Payment).filter(
                        Payment.appointment_id == appointment.id
                    ).first()

            
            if patient:
                invoice = Invoice(
                    date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                    doctor_id=user.id,
                    patient_id=patient.id,
                    appointment_id=appointment.id if appointment else None,
                    payment_id=payment.id if payment else None,
                    patient_number=str(row.get("Patient Number", ""))[:255],
                    patient_name=str(row.get("Patient Name", "")).strip("'")[:255],
                    doctor_name=str(row.get("Doctor Name", "")).strip("'")[:255],
                    invoice_number=str(row.get("Invoice Number", ""))[:255],
                    cancelled=bool(row.get("Cancelled", False)),
                    notes=str(row.get("Notes", "")),
                    description=str(row.get("Description", ""))
                )
                
                # Save invoice first to get ID
                db.add(invoice)
                db.flush()

                # Parse discount type
                discount_type = row.get("DiscountType", "").upper() if row.get("DiscountType") else None

                # Helper function to safely parse numeric values
                def safe_parse_number(value, convert_func, default=None, strip_quotes=True):
                    if pd.isna(value):
                        return default
                    try:
                        val_str = str(value).strip("'") if strip_quotes else str(value)
                        return convert_func(val_str)
                    except (ValueError, TypeError):
                        return default
                
                unit_cost = safe_parse_number(row.get("Unit Cost"), float, 0.0)
                discount = safe_parse_number(row.get("Discount"), float)
                quantity = safe_parse_number(row.get("Quantity"), int, 1)
                tax_percent = safe_parse_number(row.get("Tax Percent"), float)
                total_amount = 0.0

                invoice_item = InvoiceItem(
                    invoice_id=invoice.id,
                    treatment_name=str(row.get("Treatment Name", ""))[:255],
                    unit_cost=safe_parse_number(row.get("Unit Cost"), float, 0.0),
                    quantity=safe_parse_number(row.get("Quantity"), int, 1),
                    discount=safe_parse_number(row.get("Discount"), float),
                    discount_type=discount_type,
                    type=str(row.get("Type", ""))[:255],
                    invoice_level_tax_discount=safe_parse_number(row.get("Invoice Level Tax Discount"), float),
                    tax_name=str(row.get("Tax name", ""))[:255],
                    tax_percent=safe_parse_number(row.get("Tax Percent"), float)
                )
                db.add(invoice_item)

                item_total = unit_cost * quantity  # Base cost
            
                # Apply discount
                if discount:
                    if discount_type == "percentage":
                        item_total -= (item_total * discount / 100)
                    elif discount_type == "fixed":
                        item_total -= discount
                
                # Apply tax
                if tax_percent:
                    tax_amount = (item_total * tax_percent / 100)
                    item_total += tax_amount
                
                # Add to total invoice amount
                total_amount += item_total

                # Update invoice total
                invoice.total_amount = total_amount


        db.commit()
    except Exception as e:
        print(f"Error during bulk insert: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during bulk insert: {str(e)}"})

async def process_procedure_catalog_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing procedure catalog data")
    procedures = []
    
    # Process all rows at once using pandas operations
    df['treatment_cost'] = df['Treatment Cost'].fillna('0').astype(str).str.strip().str.strip("'")
    df['treatment_name'] = df['Treatment Name'].fillna('').astype(str).str.strip("'").str[:255] 
    df['treatment_notes'] = df['Treatment Notes'].fillna('').astype(str)
    df['locale'] = df['Locale'].fillna('').astype(str).str.strip("'").str[:50]

    try:
        # Create all ProcedureCatalog objects in memory
        procedures = []
        for _, row in df.iterrows():
            procedure =  ProcedureCatalog(
                user_id=user.id,
                treatment_name=row['treatment_name'],
                treatment_cost=row['treatment_cost'], 
                treatment_notes=row['treatment_notes'],
                locale=row['locale']
            )
            procedures.append(procedure)
            existing_treatment_name_suggestion = db.query(TreatmentNameSuggestion).filter(TreatmentNameSuggestion.treatment_name == row['treatment_name']).first()
            if not existing_treatment_name_suggestion:
                suggestion = TreatmentNameSuggestion(
                    treatment_name=row['treatment_name']
                )
                db.add(suggestion)
        # Bulk insert all records at once
        if procedures:
            db.bulk_save_objects(procedures)
            db.commit()
            
    except Exception as e:
        print(f"Error processing procedure catalog data: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error processing procedure catalog data: {str(e)}"})

async def process_data_in_background(file_path: str, user_id: str, import_log_id: str, db: Session, uuid: str):
    try:
        print(f"Starting background processing for file: {file_path}")
        import_log = db.query(ImportLog).filter(ImportLog.id == import_log_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        print(f"Found import_log {import_log_id} and user {user_id}")

        if not import_log:
            print(f"Import log with id {import_log_id} not found")
            return
        if not user:
            print(f"User with id {user_id} not found")
            return

        file_ext = os.path.splitext(file_path)[1].lower()
        print(f"File extension: {file_ext}")
        
        # Extract if zip file
        if file_ext == '.zip':
            try:
                print("Extracting zip file...")
                import_log.current_stage = "Extracting ZIP file"
                import_log.progress = 5
                db.commit()
                
                with zipfile.ZipFile(file_path, "r") as zip_ref:
                    zip_ref.extractall(f"uploads/imports/{uuid}")
                print("Zip file extracted successfully")
                
                import_log.progress = 10
                db.commit()
            except Exception as e:
                print(f"Error extracting zip file: {str(e)}")
                import_log.status = ImportStatus.FAILED
                import_log.progress = 0
                import_log.error_message = f"Failed to extract ZIP: {str(e)}"
                db.commit()
                return

        # Update status to processing
        import_log.status = ImportStatus.PROCESSING
        import_log.current_stage = "Analyzing files"
        import_log.progress = 15
        db.commit()

        # Process each CSV file
        csv_files = [f for f in os.listdir(f"uploads/imports/{uuid}") if f.endswith('.csv')]
        print(f"Found CSV files: {csv_files}")
        if not csv_files:
            print("No CSV files found")
            import_log.status = ImportStatus.FAILED
            import_log.progress = 0
            import_log.error_message = "No CSV files found in upload"
            db.commit()
            return

        # Define processing order and file name patterns
        file_types = [
            {
                "patterns": ["patients", "patient"],
                "processor": process_patient_data,
                "stage_name": "Processing Patient Data"
            },
            {
                "patterns": ["appointments", "appointment"],
                "processor": process_appointment_data,
                "stage_name": "Processing Appointment Data"
            },
            {
                "patterns": ["treatment.csv"],
                "processor": process_treatment_data,
                "stage_name": "Processing Treatment Data"
            },
            {
                "patterns": ["clinicalnotes", "clinical-notes", "clinical_notes"],
                "processor": process_clinical_note_data,
                "stage_name": "Processing Clinical Notes"
            },
            {
                "patterns": ["treatmentplans", "treatment-plans", "treatment_plans"],
                "processor": process_treatment_plan_data,
                "stage_name": "Processing Treatment Plans"
            },
            {
                "patterns": ["expenses", "expense"],
                "processor": process_expense_data,
                "stage_name": "Processing Expense Data"
            },
            {
                "patterns": ["payments", "payment"],
                "processor": process_payment_data,
                "stage_name": "Processing Payment Data"
            },
            {
                "patterns": ["invoices", "invoice"],
                "processor": process_invoice_data,
                "stage_name": "Processing Invoice Data"
            },
            {
                "patterns": ["procedure catalog", "procedure-catalog", "procedure_catalog", "procedurecatalog"],
                "processor": process_procedure_catalog_data,
                "stage_name": "Processing Procedure Catalog"
            }
        ]

        total_files = len(csv_files)
        files_processed = 0
        progress_per_file = 75 / total_files  # 75% of progress bar for file processing (15-90%)

        # Process files in order
        for file_type in file_types:
            print(f"\nProcessing file type: {file_type['patterns']}")
            for filename in csv_files:
                normalized_filename = filename.lower().replace(" ", "")
                
                # Check if current file matches any pattern for this type
                if any(pattern.replace(" ", "").lower() in normalized_filename for pattern in file_type["patterns"]):
                    print(f"\nProcessing file: {filename}")
                    try:
                        import_log.current_stage = f"{file_type['stage_name']} ({filename})"
                        import_log.current_file = filename
                        db.commit()
                        
                        print(f"Reading CSV file: {filename}")
                        df = pd.read_csv(f"uploads/imports/{uuid}/{filename}", keep_default_na=False)
                        df = df.fillna("")
                        print(f"Successfully read CSV with {len(df)} rows")
                        
                        # Call appropriate processor function
                        processor = file_type["processor"]
                        if processor in [process_patient_data, process_appointment_data, process_expense_data, 
                                      process_payment_data, process_invoice_data, process_procedure_catalog_data, process_treatment_data, process_clinical_note_data, process_treatment_plan_data]:
                            await processor(import_log, df, db, user)
                        else:
                            await processor(import_log, df, db)
                            
                        files_processed += 1
                        progress = 15 + int(files_processed * progress_per_file)
                        import_log.progress = min(progress, 90)  # Cap at 90%
                        import_log.files_processed = files_processed
                        import_log.total_files = total_files
                        db.commit()
                            
                    except Exception as e:
                        print(f"Error processing file {filename}: {str(e)}")
                        import_log.error_message = f"Error in {filename}: {str(e)}"
                        continue

        # Update import log status to completed
        import_log.status = ImportStatus.COMPLETED
        import_log.current_stage = "Import Completed"
        import_log.progress = 100
        db.commit()
        print("Import completed successfully")
        
    except Exception as e:
        print(f"Error in background processing: {str(e)}")
        if 'import_log' in locals():
            if import_log:
                import_log.status = ImportStatus.FAILED
                import_log.progress = 0
                import_log.error_message = f"Import failed: {str(e)}"
                db.commit()
                print("Updated import status to FAILED")
    finally:
        db.close()
        shutil.rmtree(f"uploads/imports/{uuid}")
        print("Database connection closed")
        
@user_router.post("/import-data",
    response_model=dict,
    status_code=200,
    summary="Import data from CSV or ZIP files",
    description="""
    Import data from CSV files or a ZIP archive containing CSV files.
    
    **Supported file formats:**
    - Single CSV file
    - ZIP archive containing multiple CSV files
    
    **Supported data types:**
    - Patients
    - Appointments 
    - Expenses
    - Payments
    - Invoices
    - Procedure catalogs
    - Treatments
    - Clinical notes
    - Treatment plans
    
    **File requirements:**
    - CSV files must have appropriate headers matching the data type
    - Data must be properly formatted according to schema
    - Files in ZIP archives must be organized by data type
    
    **Processing details:**
    - Files are validated before processing
    - Data is imported in order to maintain referential integrity 
    - Duplicate records are skipped based on unique identifiers
    - Processing happens asynchronously in background
    - Progress can be monitored via import_log_id
    
    **Progress tracking includes:**
    - Overall progress percentage (0-100%)
    - Current processing stage
    - Current file being processed
    - Files processed count
    - Total files count
    - Any error messages
    
    **Authentication:**
    - Requires valid Bearer token
    
    **Request body:**
    - file: CSV or ZIP file (form-data)
    """,
    responses={
        200: {
            "description": "Data import started successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Data import started",
                        "import_log_id": "550e8400-e29b-41d4-a716-446655440000"
                    }
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_format": {
                            "value": {"error": "Invalid file format. Only CSV and ZIP files are allowed."}
                        },
                        "invalid_data": {
                            "value": {"error": "Invalid data format in CSV file"}
                        },
                        "missing_file": {
                            "value": {"error": "No file provided"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized - Invalid or missing token"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Error processing file: {detailed error message}"}
                }
            }
        }
    }
)
async def import_data(background_tasks: BackgroundTasks,request: Request, file: UploadFile = File(...), db: Session = Depends(get_db) ):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        

        # Validate file extension
        allowed_extensions = ['.csv', '.zip']
        file_ext = os.path.splitext(str(file.filename))[1].lower()
        if file_ext not in allowed_extensions:
            return JSONResponse(status_code=400, content={"error": "Invalid file format. Only CSV and ZIP files are allowed."})
        uuid = generate_uuid()
        # Create uploads directory if it doesn't exist
        upload_dir = os.path.join("uploads", "imports", uuid)
        os.makedirs(upload_dir, exist_ok=True)
        
        # Create import log entry
        import_log = ImportLog(
            user_id=user.id,
            file_name=file.filename,
            status=ImportStatus.PENDING,
            progress=0,
            current_stage="Initializing",
            current_file=None,
            files_processed=0,
            total_files=0,
            error_message=None
        )
        db.add(import_log)
        db.commit()
        
        # Read and save file
        file_contents = await file.read()
        file_path = f"uploads/imports/{uuid}/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(file_contents)
            
        if file_ext == '.zip':
            import_log.zip_file = file_path
            db.commit()

        # Start background processing
        background_tasks.add_task(process_data_in_background, file_path, user.id, import_log.id, db, uuid)

        return JSONResponse(status_code=200, content={
            "message": "Data import started",
            "import_log_id": import_log.id
        })

    except Exception as e:
        if 'import_log' in locals():
            import_log.status = ImportStatus.FAILED
            import_log.progress = 0
            import_log.error_message = f"Failed to start import: {str(e)}"
            db.commit()
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.get("/get-import-logs",
    response_model=dict,
    status_code=200,
    summary="Get all import logs",
    description="""
    Get all import logs for the authenticated user.
    
    Returns a paginated list of import logs with details including:
    - Import ID
    - Original filename
    - Import status (pending/completed/failed) 
    - Progress percentage
    - Current stage
    - Current file being processed
    - Files processed count
    - Total files count
    - Error message (if any)
    - Creation timestamp
    
    Results are sorted by creation date in descending order (newest first).
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "Import logs retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "import_logs": [
                            {
                                "id": "uuid",
                                "file_name": "data.csv",
                                "status": "completed",
                                "progress": 100,
                                "current_stage": "Completed",
                                "current_file": "patients.csv", 
                                "files_processed": 5,
                                "total_files": 5,
                                "error_message": None,
                                "created_at": "2024-01-01T00:00:00"
                            }
                        ],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error message"}
                }
            }
        }
    }
)
async def get_import_logs(
    request: Request,
    page: int = 1,
    per_page: int = 10,
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        # Validate pagination params
        per_page = min(per_page, 100)  # Cap items per page
        page = max(page, 1)  # Ensure page is at least 1
        
        # Get total count
        total = db.query(ImportLog).filter(ImportLog.user_id == user.id).count()
        
        # Calculate pagination
        total_pages = (total + per_page - 1) // per_page
        offset = (page - 1) * per_page
        
        # Get paginated logs
        import_logs = db.query(ImportLog)\
            .filter(ImportLog.user_id == user.id)\
            .order_by(ImportLog.created_at.desc())\
            .offset(offset)\
            .limit(per_page)\
            .all()

        return JSONResponse(status_code=200, content={
            "import_logs": [
                {
                    "id": log.id,
                    "file_name": log.file_name,
                    "status": log.status.value,
                    "progress": log.progress,
                    "current_stage": log.current_stage,
                    "current_file": log.current_file,
                    "files_processed": log.files_processed,
                    "total_files": log.total_files,
                    "error_message": log.error_message,
                    "created_at": log.created_at.isoformat()
                } for log in import_logs
            ],
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            }
        })
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.post("/add-procedure-catalog",
    response_model=ProcedureCatalogResponse,
    status_code=201,
    summary="Add a new procedure catalog",
    description="""
    Add a new procedure catalog entry for the authenticated user.
    
    Required fields:
    - treatment_name: Name/title of the procedure
    - treatment_cost: Cost of the procedure
    - treatment_notes: Additional notes/description (optional)
    - locale: Currency/location code for the cost
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Notes:
    - Each user can have multiple procedure catalogs
    - Treatment costs should be in the specified locale's currency
    """,
    responses={
        201: {
            "description": "Procedure catalog created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Procedure catalog created successfully"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def add_procedure_catalog(request: Request, procedure: ProcedureCatalogSchema, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        procedure_catalog = ProcedureCatalog(
            user_id=user.id,
            treatment_name=procedure.treatment_name,
            treatment_cost=procedure.treatment_cost,
            treatment_notes=procedure.treatment_notes,
            locale=procedure.locale
        )
        db.add(procedure_catalog)
        db.commit()
        db.refresh(procedure_catalog)
        
        return JSONResponse(status_code=201, content={
            "message": "Procedure catalog created successfully",
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.get("/get-procedure-catalogs",
    response_model=dict,
    status_code=200,
    summary="Get all procedure catalogs with statistics",
    description="""
    Get all procedure catalogs for the authenticated user with detailed statistics.
    
    Returns a paginated list of procedure catalogs with details including:
    - Procedure ID
    - Treatment name 
    - Treatment cost
    - Treatment notes
    - Locale
    - Creation and update timestamps
    
    Also includes statistics for:
    - Today's procedures count and total cost
    - This month's procedures count and total cost  
    - This year's procedures count and total cost
    - Overall procedures count and total cost
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    - sort_by: Sort field (default: created_at)
    - sort_order: Sort direction - asc or desc (default: desc)
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "List of procedure catalogs with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "procedure_catalogs": [{
                            "id": "uuid",
                            "treatment_name": "Dental Cleaning",
                            "treatment_cost": "100.00", 
                            "treatment_notes": "Basic cleaning procedure",
                            "locale": "USD",
                            "created_at": "2024-01-01T00:00:00",
                            "updated_at": "2024-01-01T00:00:00"
                        }],
                        "statistics": {
                            "today": {
                                "count": 5,
                                "total_cost": "500.00"
                            },
                            "month": {
                                "count": 45,
                                "total_cost": "4500.00"
                            },
                            "year": {
                                "count": 250,
                                "total_cost": "25000.00"
                            },
                            "overall": {
                                "count": 1000,
                                "total_cost": "100000.00"
                            }
                        },
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def get_procedure_catalogs(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Get total count
        total = db.query(ProcedureCatalog).filter(ProcedureCatalog.user_id == user.id).count()
        
        # Calculate pagination
        total_pages = ceil(total / per_page)
        offset = (page - 1) * per_page

        # Get statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)

        today_stats = db.query(
            func.count(ProcedureCatalog.id).label('count'),
            func.sum(ProcedureCatalog.treatment_cost).label('total_cost')
        ).filter(
            ProcedureCatalog.user_id == user.id,
            func.date(ProcedureCatalog.created_at) == today
        ).first()

        month_stats = db.query(
            func.count(ProcedureCatalog.id).label('count'),
            func.sum(ProcedureCatalog.treatment_cost).label('total_cost')
        ).filter(
            ProcedureCatalog.user_id == user.id,
            ProcedureCatalog.created_at >= first_day_of_month
        ).first()

        year_stats = db.query(
            func.count(ProcedureCatalog.id).label('count'),
            func.sum(ProcedureCatalog.treatment_cost).label('total_cost')
        ).filter(
            ProcedureCatalog.user_id == user.id,
            ProcedureCatalog.created_at >= first_day_of_year
        ).first()

        overall_stats = db.query(
            func.count(ProcedureCatalog.id).label('count'),
            func.sum(ProcedureCatalog.treatment_cost).label('total_cost')
        ).filter(
            ProcedureCatalog.user_id == user.id
        ).first()
        
        # Get paginated results with sorting
        query = db.query(ProcedureCatalog).filter(ProcedureCatalog.user_id == user.id)
        
        if hasattr(ProcedureCatalog, sort_by):
            sort_column = getattr(ProcedureCatalog, sort_by)
            if sort_order.lower() == 'desc':
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
                
        procedure_catalogs = query.offset(offset).limit(per_page).all()

        procedure_catalogs_list = []
        for procedure_catalog in procedure_catalogs:
            procedure_catalogs_list.append({
                "id": procedure_catalog.id,
                "treatment_name": procedure_catalog.treatment_name,
                "treatment_cost": procedure_catalog.treatment_cost,
                "treatment_notes": procedure_catalog.treatment_notes,
                "locale": procedure_catalog.locale,
                "created_at": procedure_catalog.created_at.isoformat() if procedure_catalog.created_at else None,
                "updated_at": procedure_catalog.updated_at.isoformat() if procedure_catalog.updated_at else None
            })

        return JSONResponse(status_code=200, content={
            "procedure_catalogs": procedure_catalogs_list,
            "statistics": {
                "today": {
                    "count": today_stats[0] if today_stats else 0,
                    "total_cost": str(today_stats[1] if today_stats else 0)
                },
                "month": {
                    "count": month_stats[0] if month_stats else 0,
                    "total_cost": str(month_stats[1] if month_stats else 0)
                },
                "year": {
                    "count": year_stats[0] if year_stats else 0,
                    "total_cost": str(year_stats[1] if year_stats else 0)
                },
                "overall": {
                    "count": overall_stats[0] if overall_stats else 0,
                    "total_cost": str(overall_stats[1] if overall_stats else 0)
                }
            },
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            }
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})
    
@user_router.get("/get-procedure-catalog/{procedure_id}",
    response_model=ProcedureCatalogResponse,
    status_code=200,
    summary="Get a procedure catalog by ID",
    description="""
    Get a procedure catalog by its unique ID.
    
    Path parameters:
    - procedure_id: ID of the procedure catalog to get
    
    Required headers:
    - Authorization: Bearer {access_token}

    Returns:
    - procedure_catalog: Procedure catalog details
    - message: Success message
    """,
    responses={
        200: {
            "description": "Procedure catalog retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "procedure_catalog": {
                            "id": "uuid",
                            "treatment_name": "Dental Cleaning",
                            "treatment_cost": "100.00",
                            "treatment_notes": "Basic cleaning procedure",
                            "locale": "USD",
                            "created_at": "2024-01-01T00:00:00",
                            "updated_at": "2024-01-01T00:00:00"
                        },
                        "message": "Procedure catalog retrieved successfully"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Procedure catalog not found",
            "content": {
                "application/json": {
                    "example": {"error": "Procedure catalog not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def get_procedure_catalog(
    request: Request,
    procedure_id: str,
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        procedure_catalog = db.query(ProcedureCatalog).filter(
            ProcedureCatalog.id == procedure_id,
            ProcedureCatalog.user_id == user.id
        ).first()
        
        if not procedure_catalog:
            return JSONResponse(status_code=404, content={"error": "Procedure catalog not found"})
        
        return JSONResponse(status_code=200, content={
            "procedure_catalog": {
                "id": procedure_catalog.id,
                "treatment_name": procedure_catalog.treatment_name,
                "treatment_cost": procedure_catalog.treatment_cost,
                "treatment_notes": procedure_catalog.treatment_notes,
                "locale": procedure_catalog.locale,
                "created_at": procedure_catalog.created_at.isoformat() if procedure_catalog.created_at else None,
                "updated_at": procedure_catalog.updated_at.isoformat() if procedure_catalog.updated_at else None
            },
            "message": "Procedure catalog retrieved successfully"
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})
    
@user_router.get("/search-procedure-catalog",
    response_model=dict,
    status_code=200,
    summary="Search and analyze procedure catalogs",
    description="""
    Search for procedure catalogs by name or description with detailed statistics.
    
    Query parameters:
    - search_query: Search query to filter procedure catalogs by name or notes (optional)
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    - min_cost: Minimum treatment cost filter (optional)
    - max_cost: Maximum treatment cost filter (optional)
    
    Returns:
    - procedure_catalogs: List of matching procedure catalogs with details
    - statistics: Usage and cost statistics broken down by:
        - Today's procedures and total cost
        - This month's procedures and total cost
        - This year's procedures and total cost
        - Overall procedures and total cost
    - pagination: Pagination details including total items and pages
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "Procedure catalogs and statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "procedure_catalogs": [
                            {
                                "id": "uuid",
                                "treatment_name": "Dental Cleaning",
                                "treatment_cost": "100.00",
                                "treatment_notes": "Basic cleaning procedure",
                                "locale": "USD",
                                "created_at": "2024-01-01T00:00:00",
                                "updated_at": "2024-01-01T00:00:00"
                            }
                        ],
                        "statistics": {
                            "today": {
                                "count": 5,
                                "total_cost": "500.00"
                            },
                            "month": {
                                "count": 45,
                                "total_cost": "4500.00"  
                            },
                            "year": {
                                "count": 250,
                                "total_cost": "25000.00"
                            },
                            "overall": {
                                "count": 1000,
                                "total_cost": "100000.00"
                            }
                        },
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        },
                        "message": "Procedure catalogs retrieved successfully"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "example": {"error": "User not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def search_procedure_catalog(
    request: Request, 
    search_query: Optional[str] = None,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    min_cost: Optional[float] = Query(default=None, description="Minimum treatment cost filter"),
    max_cost: Optional[float] = Query(default=None, description="Maximum treatment cost filter"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Build base query
        query = db.query(ProcedureCatalog).filter(ProcedureCatalog.user_id == user.id).order_by(ProcedureCatalog.created_at.desc())
        
        # Add search filter if search_query provided
        if search_query:
            query = query.filter(
                (ProcedureCatalog.treatment_name.ilike(f"%{search_query}%")) |
                (ProcedureCatalog.treatment_notes.ilike(f"%{search_query}%"))
            )
        
        # Add cost filters if provided
        if min_cost is not None:
            query = query.filter(func.cast(ProcedureCatalog.treatment_cost, Float) >= min_cost)
        if max_cost is not None:
            query = query.filter(func.cast(ProcedureCatalog.treatment_cost, Float) <= max_cost)
            
        # Get total count
        total = query.count()
        
        # Calculate pagination
        total_pages = ceil(total / per_page)
        offset = (page - 1) * per_page
        
        # Get paginated results
        procedure_catalogs = query.offset(offset).limit(per_page).all()
        
        # Get statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)
        
        stats_query = db.query(
            func.count().label('count'),
            func.sum(func.cast(ProcedureCatalog.treatment_cost, Float)).label('total_cost')
        ).filter(ProcedureCatalog.user_id == user.id)
        
        today_stats = stats_query.filter(func.date(ProcedureCatalog.created_at) == today).first()
        month_stats = stats_query.filter(func.date(ProcedureCatalog.created_at) >= first_day_of_month).first()
        year_stats = stats_query.filter(func.date(ProcedureCatalog.created_at) >= first_day_of_year).first()
        overall_stats = stats_query.first()
        
        procedure_catalogs_list = []
        for procedure_catalog in procedure_catalogs:
            procedure_catalogs_list.append({
                "id": procedure_catalog.id,
                "treatment_name": procedure_catalog.treatment_name,
                "treatment_cost": procedure_catalog.treatment_cost,
                "treatment_notes": procedure_catalog.treatment_notes,
                "locale": procedure_catalog.locale,
                "created_at": procedure_catalog.created_at.isoformat() if procedure_catalog.created_at else None,
                "updated_at": procedure_catalog.updated_at.isoformat() if procedure_catalog.updated_at else None
            })
        
        return JSONResponse(status_code=200, content={
            "procedure_catalogs": procedure_catalogs_list,
            "statistics": {
                "today": {
                    "count": today_stats.count if today_stats else 0,
                    "total_cost": str(round(today_stats.total_cost if today_stats and today_stats.total_cost else 0, 2))
                },
                "month": {
                    "count": month_stats.count if month_stats else 0,
                    "total_cost": str(round(month_stats.total_cost if month_stats and month_stats.total_cost else 0, 2))
                },
                "year": {
                    "count": year_stats.count if year_stats else 0,
                    "total_cost": str(round(year_stats.total_cost if year_stats and year_stats.total_cost else 0, 2))
                },
                "overall": {
                    "count": overall_stats.count if overall_stats else 0,
                    "total_cost": str(round(overall_stats.total_cost if overall_stats and overall_stats.total_cost else 0, 2))
                }
            },
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            },
            "message": "Procedure catalogs retrieved successfully"
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})
    
@user_router.patch("/update-procedure-catalog/{procedure_id}",
    response_model=ProcedureCatalogResponse,
    status_code=200,
    summary="Update an existing procedure catalog entry",
    description="""
    Update an existing procedure catalog entry.
    
    Path parameters:
    - procedure_id: ID of the procedure catalog to update
    
    Updatable fields (all optional):
    - treatment_name: Name/title of the procedure
    - treatment_cost: Cost of the procedure
    - treatment_notes: Additional notes/description
    - locale: Currency/location code for the cost
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Notes:
    - Only the provided fields will be updated
    - Other fields will retain their existing values
    - Only the owner can update their procedure catalogs
    """,
    responses={
        200: {
            "description": "Procedure catalog updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Procedure catalog updated successfully"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user": {
                            "value": {"error": "User not found"}
                        },
                        "procedure": {
                            "value": {"error": "Procedure catalog not found"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def update_procedure_catalog(
    request: Request, 
    procedure_id: str,
    procedure: ProcedureCatalogUpdateSchema, 
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        procedure_catalog = db.query(ProcedureCatalog).filter(
            ProcedureCatalog.id == procedure_id,
            ProcedureCatalog.user_id == user.id
        ).first()
        if not procedure_catalog:
            return JSONResponse(status_code=404, content={"error": "Procedure catalog not found"})
        
        if procedure.treatment_name is not None:
            procedure_catalog.treatment_name = str(procedure.treatment_name)
        if procedure.treatment_cost is not None:
            procedure_catalog.treatment_cost = str(procedure.treatment_cost)
        if procedure.treatment_notes is not None:
            procedure_catalog.treatment_notes = str(procedure.treatment_notes)
        if procedure.locale is not None:
            procedure_catalog.locale = str(procedure.locale)
        
        db.commit()
        db.refresh(procedure_catalog)
        
        return JSONResponse(status_code=200, content={
            "message": "Procedure catalog updated successfully"
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.delete("/delete-procedure-catalog/{procedure_id}",
    status_code=200,
    summary="Delete a procedure catalog",
    description="""
    Delete an existing procedure catalog entry.
    
    Path parameters:
    - procedure_id: ID of the procedure catalog to delete
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Notes:
    - Only the owner can delete their procedure catalogs
    - This action cannot be undone
    - Associated data may also be affected
    """,
    responses={
        200: {
            "description": "Procedure catalog deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Procedure catalog deleted successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user": {
                            "value": {"error": "User not found"}
                        },
                        "procedure": {
                            "value": {"error": "Procedure catalog not found"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def delete_procedure_catalog(request: Request, procedure_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        procedure_catalog = db.query(ProcedureCatalog).filter(
            ProcedureCatalog.id == procedure_id,
            ProcedureCatalog.user_id == user.id
        ).first()
        if not procedure_catalog:
            return JSONResponse(status_code=404, content={"error": "Procedure catalog not found"})
        
        db.delete(procedure_catalog)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Procedure catalog deleted successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.get("/get-all-users",
    response_model=dict,
    status_code=200,
    summary="Get all users with statistics",
    description="""
    Get all users in the system with detailed statistics.
    
    Returns a paginated list of users with details including:
    - User ID
    - Name
    - Email
    - Phone
    - User type
    - Bio
    - Profile picture URL
    - Creation and update timestamps
    
    Also includes statistics for:
    - Today's registered users count
    - This month's registered users count
    - This year's registered users count
    - Overall users count
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    - sort_by: Sort field (default: created_at)
    - sort_order: Sort direction - asc or desc (default: desc)
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Notes:
    - Sensitive information is excluded
    - Results include all user types
    """,
    responses={
        200: {
            "description": "List of all users with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "users": [{
                            "id": "uuid",
                            "name": "John Doe",
                            "email": "john@example.com",
                            "phone": "+1234567890",
                            "user_type": "doctor",
                            "bio": "Experienced dentist",
                            "profile_pic": "url/to/picture.jpg",
                            "created_at": "2024-01-01T00:00:00",
                            "updated_at": "2024-01-01T00:00:00"
                        }],
                        "statistics": {
                            "today": {
                                "count": 5
                            },
                            "month": {
                                "count": 45
                            },
                            "year": {
                                "count": 250
                            },
                            "overall": {
                                "count": 1000
                            }
                        },
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user": {
                            "value": {"error": "User not found"}
                        },
                        "no_users": {
                            "value": {"error": "No users found"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def get_all_users(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Get total count
        total = db.query(User).count()
        if total == 0:
            return JSONResponse(status_code=404, content={"error": "No users found"})
            
        # Calculate pagination
        total_pages = ceil(total / per_page)
        offset = (page - 1) * per_page

        # Get statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)

        stats_query = db.query(func.count(User.id).label('count'))

        today_stats = stats_query.filter(func.date(User.created_at) == today).first()
        month_stats = stats_query.filter(func.date(User.created_at) >= first_day_of_month).first()
        year_stats = stats_query.filter(func.date(User.created_at) >= first_day_of_year).first()
        overall_stats = stats_query.first()
        
        # Build base query
        query = db.query(User)
        
        # Add sorting
        if hasattr(User, sort_by):
            sort_column = getattr(User, sort_by)
            if sort_order.lower() == 'desc':
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        
        # Get paginated users
        users = query.offset(offset).limit(per_page).all()
        
        users_list = []
        for user in users:
            user_data = {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "phone": user.phone,
                "user_type": user.user_type,
                "bio": user.bio,
                "profile_pic": user.profile_pic,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            }
            users_list.append(user_data)

        return JSONResponse(status_code=200, content={
            "users": users_list,
            "statistics": {
                "today": {
                    "count": today_stats.count if today_stats else 0
                },
                "month": {
                    "count": month_stats.count if month_stats else 0
                },
                "year": {
                    "count": year_stats.count if year_stats else 0
                },
                "overall": {
                    "count": overall_stats.count if overall_stats else 0
                }
            },
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            }
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.get("/doctor-list",
    response_model=dict,
    status_code=200,
    summary="Get all doctors with statistics",
    description="""
    Get all doctors in the system with detailed statistics.
    
    Returns a paginated list of users with user_type='doctor' including:
    - Doctor ID
    - Name
    - Email
    - Phone
    - Bio
    - Profile picture URL
    - Creation and update timestamps
    
    Also includes statistics for:
    - Today's registered doctors count
    - This month's registered doctors count
    - This year's registered doctors count
    - Overall doctors count
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    - sort_by: Sort field (default: created_at)
    - sort_order: Sort direction - asc or desc (default: desc)
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Notes:
    - Only returns users with type 'doctor'
    - Sensitive information is excluded
    - Used for displaying doctor selection lists
    """,
    responses={
        200: {
            "description": "List of all doctors with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "doctors": [{
                            "id": "uuid",
                            "name": "Dr. John Doe",
                            "email": "dr.john@example.com",
                            "phone": "+1234567890",
                            "user_type": "doctor",
                            "bio": "Experienced dentist",
                            "profile_pic": "url/to/picture.jpg",
                            "created_at": "2024-01-01T00:00:00",
                            "updated_at": "2024-01-01T00:00:00"
                        }],
                        "statistics": {
                            "today": {
                                "count": 2
                            },
                            "month": {
                                "count": 15
                            },
                            "year": {
                                "count": 75
                            },
                            "overall": {
                                "count": 250
                            }
                        },
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user": {
                            "value": {"error": "User not found"}
                        },
                        "no_doctors": {
                            "value": {"error": "No doctors found"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Unexpected error: {error details}"}
                }
            }
        }
    }
)
async def get_doctor_list(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Get total count
        total = db.query(User).filter(User.user_type == "doctor").count()
        if total == 0:
            return JSONResponse(status_code=404, content={"error": "No doctors found"})
            
        # Calculate pagination
        total_pages = ceil(total / per_page)
        offset = (page - 1) * per_page

        # Get statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)

        stats_query = db.query(func.count(User.id).label('count')).filter(User.user_type == "doctor")

        today_stats = stats_query.filter(func.date(User.created_at) == today).first()
        month_stats = stats_query.filter(func.date(User.created_at) >= first_day_of_month).first()
        year_stats = stats_query.filter(func.date(User.created_at) >= first_day_of_year).first()
        overall_stats = stats_query.first()
        
        # Build base query
        query = db.query(User).filter(User.user_type == "doctor")
        
        # Add sorting
        if hasattr(User, sort_by):
            sort_column = getattr(User, sort_by)
            if sort_order.lower() == 'desc':
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        
        # Get paginated doctors
        doctors = query.offset(offset).limit(per_page).all()
        
        doctors_list = []
        for doctor in doctors:
            doctor_data = {
                "id": doctor.id,
                "name": doctor.name,
                "email": doctor.email,
                "phone": doctor.phone,
                "user_type": doctor.user_type,
                "bio": doctor.bio,
                "profile_pic": doctor.profile_pic,
                "created_at": doctor.created_at.isoformat() if doctor.created_at else None,
                "updated_at": doctor.updated_at.isoformat() if doctor.updated_at else None
            }
            doctors_list.append(doctor_data)

        return JSONResponse(status_code=200, content={
            "doctors": doctors_list,
            "statistics": {
                "today": {
                    "count": today_stats.count if today_stats else 0
                },
                "month": {
                    "count": month_stats.count if month_stats else 0
                },
                "year": {
                    "count": year_stats.count if year_stats else 0
                },
                "overall": {
                    "count": overall_stats.count if overall_stats else 0
                }
            },
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            }
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})
    
@user_router.get("/dashboard",
    response_model=dict,
    status_code=200,
    summary="Get dashboard statistics", 
    description="""
    Get comprehensive dashboard statistics for the authenticated user including:
    - Patient statistics (total count, recent patients)
    - Appointment metrics (today's appointments, upcoming, total count)
    - Clinical data (total notes, recent activity)
    - Financial overview (monthly earnings, recent transactions)
    - Key performance indicators
    """
)
async def get_dashboard(request: Request, clinic_id: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if clinic_id:
            clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
            if not clinic:
                return JSONResponse(status_code=404, content={"error": "Clinic not found"})

        # Base query filters
        base_filters = [Patient.doctor_id == user.id]
        if clinic_id:
            base_filters.append(Patient.clinic_id == clinic_id)

        today = datetime.now().date()
        current_month_start = today.replace(day=1)

        # Patient Statistics
        total_patients = db.query(Patient).filter(*base_filters).count()
        recent_patients = db.query(Patient).filter(*base_filters).order_by(Patient.created_at.desc()).limit(10).all()
        new_patients_this_month = db.query(Patient).filter(
            *base_filters,
            Patient.created_at >= current_month_start
        ).count()

        # Appointment Statistics
        appointments_query = db.query(Appointment).filter(
            Appointment.doctor_id == user.id,
            *([Appointment.clinic_id == clinic_id] if clinic_id else [])
        )
        
        total_appointments = appointments_query.count()
        today_appointments = appointments_query.filter(
            Appointment.appointment_date >= today,
            Appointment.appointment_date < today + timedelta(days=1)
        ).order_by(Appointment.appointment_date.asc()).all()
        
        upcoming_appointments = appointments_query.filter(
            Appointment.appointment_date > today,
            Appointment.status == AppointmentStatus.SCHEDULED
        ).count()

        # Clinical Notes Statistics
        clinical_notes_query = db.query(ClinicalNote).filter(
            ClinicalNote.doctor_id == user.id,
            *([ClinicalNote.clinic_id == clinic_id] if clinic_id else [])
        )
        total_clinical_notes = clinical_notes_query.count()
        recent_clinical_notes = clinical_notes_query.order_by(ClinicalNote.created_at.desc()).limit(5).count()
        
        # Financial Statistics
        payments_query = db.query(Payment).filter(
            Payment.doctor_id == user.id,
            Payment.cancelled == False,
            *([Payment.clinic_id == clinic_id] if clinic_id else [])
        )
        
        monthly_payments = payments_query.filter(Payment.date >= current_month_start).all()
        monthly_earnings = sum(payment.amount_paid or 0 for payment in monthly_payments)
        
        recent_transactions = payments_query.order_by(Payment.created_at.desc()).limit(10).all()
        
        # Calculate average daily earnings this month
        days_in_month = (today - current_month_start).days + 1
        avg_daily_earnings = monthly_earnings / days_in_month if days_in_month > 0 else 0

        return JSONResponse(status_code=200, content={
            "patient_statistics": {
                "total_patients": total_patients,
                "new_patients_this_month": new_patients_this_month,
                "recent_patients": [{
                    "id": patient.id,
                    "name": patient.name,
                    "mobile_number": patient.mobile_number,
                    "email": patient.email,
                    "gender": patient.gender.value,
                    "created_at": patient.created_at.strftime("%Y-%m-%d %H:%M")
                } for patient in recent_patients]
            },
            "appointment_statistics": {
                "total_appointments": total_appointments,
                "upcoming_appointments": upcoming_appointments,
                "today_appointments": [{
                    "id": appt.id,
                    "patient_name": appt.patient_name,
                    "time": appt.appointment_date.strftime("%H:%M"),
                    "status": appt.status.value,
                    "notes": appt.notes
                } for appt in today_appointments]
            },
            "clinical_statistics": {
                "total_notes": total_clinical_notes,
                "recent_notes_count": recent_clinical_notes
            },
            "financial_statistics": {
                "monthly_earnings": round(monthly_earnings, 2),
                "average_daily_earnings": round(avg_daily_earnings, 2),
                "recent_transactions": [{
                    "date": payment.date.strftime("%Y-%m-%d %H:%M"),
                    "patient_name": payment.patient_name,
                    "amount": payment.amount_paid,
                    "payment_mode": payment.payment_mode,
                    "status": payment.status,
                    "receipt_number": payment.receipt_number
                } for payment in recent_transactions]
            }
        })

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})