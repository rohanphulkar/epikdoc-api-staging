from fastapi import APIRouter, Depends, Request, File, UploadFile, BackgroundTasks, Query, WebSocket
from db.db import get_db, SessionLocal
from sqlalchemy.orm import Session
from .models import User, ImportLog, ImportStatus, Clinic, generate_unique_color
from .schemas import *
from fastapi.responses import StreamingResponse, JSONResponse
from typing import AsyncGenerator 
from datetime import datetime, timedelta
from utils.auth import (
    validate_email, validate_phone, validate_password, signJWT, decodeJWT,
    verify_password, get_password_hash, generate_reset_token, verify_token, decode_token
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
import json, shutil
from math import ceil
from sqlalchemy import func
from suggestion.models import *
import random
import asyncio
from multiprocessing import Process

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
       
    3. Email OTP:
       - email: Registered email address (will trigger OTP flow)
    
    On successful email+password login:
    - Updates last_login timestamp
    - Generates JWT access token
    - Returns token and success message
    
    On successful phone/email submission for OTP:
    - Sends OTP to the phone number/email
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
                        "otp_login": {
                            "value": {
                                "message": "OTP sent successfully"
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
                            "value": {"error": "Either email (with/without password) or phone number is required"}
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
            return JSONResponse(status_code=400, content={"error": "Either email (with/without password) or phone number is required"})
        
        # Phone login flow - trigger OTP
        if user.phone:
            db_user = db.query(User).filter(User.phone == user.phone).first()
            if not db_user:
                return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
            
            if not db_user.is_active:
                return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})
            
            # Generate OTP and set expiry
            otp = random.randint(100000, 999999)
            setattr(db_user, 'otp', otp)
            setattr(db_user, 'otp_expiry', datetime.now() + timedelta(minutes=10))
            if not db_user.color_code:
                setattr(db_user, 'color_code', generate_unique_color())
            db.commit()
            db.refresh(db_user)
            
            # Send OTP via SMS
            if send_otp(str(user.phone), str(otp)):
                return JSONResponse(status_code=200, content={"message": "OTP sent to your phone number"})
            else:
                return JSONResponse(status_code=500, content={"error": "Failed to send OTP"})
        
        # Email login flow
        if user.email:
            db_user = db.query(User).filter(User.email == user.email).first()
            
            if not db_user:
                return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
            
            if not db_user.is_active:
                return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})

            # Password login
            if user.password:
                if not verify_password(user.password, str(db_user.password)):
                    return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
                
                setattr(db_user, 'last_login', datetime.now())
                if not db_user.color_code:
                    setattr(db_user, 'color_code', generate_unique_color())
                db.commit()
                db.refresh(db_user)
                
                jwt_token = signJWT(str(db_user.id))
                return JSONResponse(status_code=200, content={
                    "access_token": jwt_token["access_token"], 
                    "token_type": "bearer", 
                    "message": "Login successful",
                    "clinic_id": db_user.default_clinic_id
                })
            
            # Email OTP login
            else:
                otp = random.randint(1000, 9999)
                setattr(db_user, 'otp', otp)
                setattr(db_user, 'otp_expiry', datetime.now() + timedelta(minutes=10))
                if not db_user.color_code:
                    setattr(db_user, 'color_code', generate_unique_color())
                db.commit()
                db.refresh(db_user)
                
                if send_otp_email(db_user.email, str(otp)):
                    return JSONResponse(status_code=200, content={"message": "OTP sent to your email"})
                else:
                    return JSONResponse(status_code=500, content={"error": "Failed to send OTP"})

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
        
        # Generate new OTP and update expiry
        otp = random.randint(1000, 9999)
        setattr(db_user, 'otp', otp)
        setattr(db_user, 'otp_expiry', datetime.now() + timedelta(minutes=10))
        db.commit()
        db.refresh(db_user)
        
        # Send OTP via SMS
        if send_otp(str(user.phone), str(otp)):
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
        
        # Find user with matching OTP
        db_user = db.query(User).filter(User.otp == user.otp).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Check if OTP is expired
        if db_user.otp_expiry and db_user.otp_expiry < datetime.now():
            return JSONResponse(status_code=400, content={"error": "OTP expired"})
        
        # Verify OTP matches
        if db_user.otp != user.otp:
            return JSONResponse(status_code=400, content={"error": "Invalid OTP"})
        
        # Reset OTP and expiry after successful verification
        setattr(db_user, 'otp', None)
        setattr(db_user, 'otp_expiry', None)
        setattr(db_user, 'last_login', datetime.now())
        db.commit()
        db.refresh(db_user)
        
        # Generate JWT token
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
      - Basic info (name, email, phone, bio, color_code)
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
            "color_code": user.color_code
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
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Clinic created successfully", "new_clinic": new_clinic.id})
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
            is_default = clinic.id == user.default_clinic_id or False
            clinics_data.append({
                "id": str(clinic.id),
                "name": clinic.name,
                "speciality": clinic.speciality,
                "address": clinic.address,
                "city": clinic.city,
                "country": clinic.country,
                "phone": clinic.phone,
                "email": clinic.email,
                "is_default":is_default
            })

        return JSONResponse(status_code=200, content={"clinics": clinics_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.get("/search-clinic",
    response_model=dict,
    status_code=200,
    summary="Search clinics",
    description="""
    Search and filter clinics associated with the authenticated user.
    
    Query parameters:
    - query: General search term that matches against multiple fields
    - name: Filter by clinic name
    - speciality: Filter by clinic speciality 
    - city: Filter by city
    - country: Filter by country
    - email: Filter by email
    - phone: Filter by phone number
    
    Returns a list of matching clinics with their details.
    """,
    responses={
        200: {
            "description": "List of matching clinics",
            "content": {
                "application/json": {
                    "example": {
                        "clinics": [
                            {
                                "id": "uuid",
                                "name": "Clinic Name",
                                "speciality": "Cardiology",
                                "address": "123 Street",
                                "city": "City",
                                "country": "Country", 
                                "phone": "1234567890",
                                "email": "clinic@email.com",
                                "is_default": True
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
async def search_clinic(
    request: Request,
    query: Optional[str] = None,
    name: Optional[str] = None,
    speciality: Optional[str] = None, 
    city: Optional[str] = None,
    country: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        # Verify user token
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        # Start with base query of user's clinics
        from sqlalchemy import or_
        from auth.models import doctor_clinics
        
        clinic_query = db.query(Clinic).join(doctor_clinics).filter(doctor_clinics.c.doctor_id == user.id)

        # Apply search if query parameter is provided
        if query:
            search = f"%{query}%"
            clinic_query = clinic_query.filter(
                or_(
                    Clinic.name.ilike(search),
                    Clinic.speciality.ilike(search),
                    Clinic.city.ilike(search),
                    Clinic.country.ilike(search),
                    Clinic.email.ilike(search),
                    Clinic.phone.ilike(search)
                )
            )

        # Apply individual filters if provided
        if name:
            clinic_query = clinic_query.filter(Clinic.name.ilike(f"%{name}%"))
        if speciality:
            clinic_query = clinic_query.filter(Clinic.speciality.ilike(f"%{speciality}%"))
        if city:
            clinic_query = clinic_query.filter(Clinic.city.ilike(f"%{city}%"))
        if country:
            clinic_query = clinic_query.filter(Clinic.country.ilike(f"%{country}%"))
        if email:
            clinic_query = clinic_query.filter(Clinic.email.ilike(f"%{email}%"))
        if phone:
            clinic_query = clinic_query.filter(Clinic.phone.ilike(f"%{phone}%"))

        # Execute query and format results
        clinics = clinic_query.all()
        clinics_data = []
        for clinic in clinics:
            is_default = clinic.id == user.default_clinic_id
            clinics_data.append({
                "id": str(clinic.id),
                "name": clinic.name,
                "speciality": clinic.speciality,
                "address": clinic.address,
                "city": clinic.city,
                "country": clinic.country,
                "phone": clinic.phone,
                "email": clinic.email,
                "is_default": is_default
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
    
@user_router.delete("/clinic/delete/{clinic_id}",
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
        
        clinics = db.query(Clinic).filter(Clinic.doctors.any(User.id == user.id)).all()
        if len(clinics) == 1:
            return JSONResponse(status_code=400, content={"error": "You cannot delete your only clinic"})
        
        # Update default clinic before deleting if needed
        if user.default_clinic_id == clinic_id:
            # Find another clinic to set as default
            new_default = next((c for c in clinics if c.id != clinic_id), None)
            if new_default:
                user.default_clinic_id = new_default.id
                db.commit()
        
        # Remove clinic association from user
        clinic.doctors.remove(user)
        db.commit()
        
        # Now delete the clinic
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
        # Get origin from headers or base URL string
        origin = str(request.headers.get('origin', '') or request.base_url)
        # Clean up trailing slash if present
        origin = origin.rstrip('/')
        reset_link = f"{origin}/newpassword/{reset_token}"
        
        setattr(db_user, 'reset_token', reset_token)
        setattr(db_user, 'reset_token_expiry', datetime.now() + timedelta(hours=3))
        
        db.commit()
        db.refresh(db_user)

        # Create background tasks instance
        background_tasks = BackgroundTasks()
        
        # Add email sending task to background tasks
        background_tasks.add_task(send_forgot_password_email, user.email, reset_link)
        
        # Return response with background tasks
        return JSONResponse(
            status_code=200,
            content={"message": "Password reset email sent, please check your email for the reset link"},
            background=background_tasks
        )
            
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
            return JSONResponse(status_code=404, content={"error": "Invalid or expired reset token"})
            
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
        form = {}
        body = {}
        
        # Check content type to determine how to read the request
        content_type = request.headers.get("content-type", "")
        
        if "multipart/form-data" in content_type:
            # Handle multipart form data
            form = await request.form()
            if 'json' in form:
                try:
                    json_str = str(form['json'])
                    body = json.loads(json_str)
                except json.JSONDecodeError:
                    return JSONResponse(status_code=400, content={"error": "Invalid JSON format in form data"})
        else:
            # Handle raw JSON body
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body = json.loads(body_bytes)
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
            file_extension = os.path.splitext(image.filename)[1] if image.filename else ".jpg"
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
    This action cannot be undone. All user data including appointments, patients, payments, treatments, invoices, 
    clinical notes, x-rays, predictions and other associated records will be permanently deleted.
    
    **Process:**
    - Deletes all patient records associated with the user
    - Removes all clinical notes and their attachments
    - Deletes all payment and invoice records
    - Removes all x-rays and prediction data
    - Finally deletes the user account itself
    
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
                    "example": {"error": "An unexpected error occurred while deleting profile"}
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
        
        # Use a transaction with no autoflush to prevent premature constraint checks
        with db.no_autoflush:
            # Get all patients for this doctor
            patients = db.query(Patient).filter(Patient.doctor_id == db_user.id).all()
            
            for patient in patients:
                # Handle foreign key constraints by breaking relationships first
                
                # 1. Handle invoices and payments
                # First, break the relationship between invoices and payments
                invoices = db.query(Invoice).filter(Invoice.patient_id == patient.id).all()
                for invoice in invoices:
                    # Set payment_id to NULL to break the foreign key constraint
                    if invoice.payment_id is not None:
                        invoice.payment_id = None
                        db.add(invoice)
                
                # Flush to ensure the payment_id is set to NULL in the database
                db.flush()
                
                # 2. Handle payments and appointments
                # Break the relationship between payments and appointments
                payments = db.query(Payment).filter(Payment.patient_id == patient.id).all()
                for payment in payments:
                    if payment.appointment_id is not None:
                        payment.appointment_id = None
                        db.add(payment)
                
                # Flush to ensure the appointment_id is set to NULL in the database
                db.flush()
                
                # 3. Delete invoice items
                for invoice in invoices:
                    db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).delete()
                
                # 4. Now it's safe to delete invoices
                db.query(Invoice).filter(Invoice.patient_id == patient.id).delete()
                
                # 5. Delete payments
                db.query(Payment).filter(Payment.patient_id == patient.id).delete()
                
                # 6. Delete appointments
                db.query(Appointment).filter(Appointment.patient_id == patient.id).delete()
                
                # 7. Handle clinical notes and related records
                clinical_notes = db.query(ClinicalNote).filter(ClinicalNote.patient_id == patient.id).all()
                for note in clinical_notes:
                    # Delete all related records first
                    db.query(ClinicalNoteAttachment).filter(ClinicalNoteAttachment.clinical_note_id == note.id).delete()
                    db.query(ClinicalNoteTreatment).filter(ClinicalNoteTreatment.clinical_note_id == note.id).delete()
                    db.query(Medicine).filter(Medicine.clinical_note_id == note.id).delete()
                    db.query(Complaint).filter(Complaint.clinical_note_id == note.id).delete()
                    db.query(Diagnosis).filter(Diagnosis.clinical_note_id == note.id).delete()
                    db.query(VitalSign).filter(VitalSign.clinical_note_id == note.id).delete()
                    db.query(Notes).filter(Notes.clinical_note_id == note.id).delete()
                
                # 8. Now delete the clinical notes
                db.query(ClinicalNote).filter(ClinicalNote.patient_id == patient.id).delete()
                
                # 9. Finally delete the patient
                db.delete(patient)
            
            # Handle X-rays and predictions
            xrays = db.query(XRay).filter(XRay.doctor == db_user.id).all()
            for xray in xrays:
                # Set clinic to NULL to break foreign key constraint
                if xray.clinic is not None:
                    xray.clinic = None
                    db.add(xray)
                
                # Delete predictions and related records
                predictions = db.query(Prediction).filter(Prediction.xray_id == xray.id).all()
                for prediction in predictions:
                    # Delete legends and their related records
                    legends = db.query(Legend).filter(Legend.prediction_id == prediction.id).all()
                    for legend in legends:
                        db.query(DeletedLegend).filter(DeletedLegend.legend_id == legend.id).delete()
                        db.delete(legend)
                    db.delete(prediction)
                
                # Now delete the x-ray
                db.delete(xray)
            
            # Delete expenses
            db.query(Expense).filter(Expense.doctor_id == db_user.id).delete()
            
            # Handle import logs
            import_logs = db.query(ImportLog).filter(ImportLog.user_id == db_user.id).all()
            for log in import_logs:
                # Set clinic_id to NULL to break foreign key constraint
                if log.clinic_id is not None:
                    # Use update method instead of direct attribute assignment
                    db.query(ImportLog).filter(ImportLog.id == log.id).update({"clinic_id": None})
                db.flush()
                db.delete(log)
            
            # Set default_clinic_id to NULL before proceeding
            if db_user.default_clinic_id is not None:
                db_user.default_clinic_id = None
                db.add(db_user)
                db.flush()
            
            # Handle clinics
            # First remove the user from the doctor_clinics association table
            from auth.models import doctor_clinics
            db.execute(doctor_clinics.delete().where(doctor_clinics.c.doctor_id == db_user.id))
            
            # Get clinics created by this user (assuming they're the only doctor)
            user_clinics = []
            for clinic in db_user.clinics:
                # Check if this is the only doctor for this clinic
                if len(clinic.doctors) <= 1:
                    user_clinics.append(clinic)
            
            # Delete each clinic that only has this doctor
            for clinic in user_clinics:
                # Update any remaining references to this clinic
                db.query(Patient).filter(Patient.clinic_id == clinic.id).update({"clinic_id": None})
                db.query(XRay).filter(XRay.clinic == clinic.id).update({"clinic": None})
                
                # Now delete the clinic
                db.delete(clinic)
            
            # Handle procedure catalog entries
            db.query(ProcedureCatalog).filter(ProcedureCatalog.user_id == db_user.id).delete()
            
            # Finally delete the user
            db.delete(db_user)
            
            # Commit all changes at once
            db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Profile deleted successfully"})
        
    except Exception as e:
        db.rollback()
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
        return JSONResponse(status_code=200, content={"access_token": jwt_token["access_token"], "token_type": "bearer", "message": "Google login successful", "clinic_id": db_user.default_clinic_id})
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

def clean_list_of_dicts(l):
    result = []
    for d in l:
        cleaned_dict = {
            k: v.date().isoformat() if isinstance(v, pd.Timestamp) else v.strip("'") if isinstance(v, str) else v
            for k, v in d.items()
        }
        result.append(cleaned_dict)
    return result

total_rows = 0
rows_processed = 0
percentage_completed = 0
total_progress = 100

def update_progress(processed, total, importLog, db: Session):
    global percentage_completed, rows_processed
    rows_processed += processed
    
    # Calculate new percentage
    new_percentage = min((rows_processed / total) * 100, 100)
    
    # Only update if percentage has increased by at least 1%
    if int(new_percentage) > int(percentage_completed) or new_percentage >= 100:
        percentage_completed = new_percentage
        importLog.progress = percentage_completed
        db.commit()
    else:
        percentage_completed = new_percentage

async def process_patient_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing patient data")
    
    # Pre-process gender mapping - fix the map function to handle pandas Series
    def gender_mapper(x):
        x_str = str(x).lower()
        return Gender.FEMALE if "f" in x_str or "female" in x_str else Gender.MALE
    
    # Convert date columns once and handle NaT values
    dob_series = pd.to_datetime(df["Date of Birth"].astype(str), errors='coerce')
    anniversary_series = pd.to_datetime(df["Anniversary Date"].astype(str), errors='coerce')

    # Initialize progress tracking
    global total_rows, rows_processed, percentage_completed, total_progress

    # Prepare bulk insert
    new_patients = []
    
    for idx, row in df.iterrows():
        try:
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            patient_number = str(row.get("Patient Number", "")).strip("'")
            
            # Handle NaT values for dates by converting to None - use iloc for proper indexing
            dob = None if pd.isna(dob_series.iloc[idx]) else dob_series.iloc[idx].to_pydatetime()
            anniversary = None if pd.isna(anniversary_series.iloc[idx]) else anniversary_series.iloc[idx].to_pydatetime()

            # Check if patient already exists for this doctor
            existing_patient = db.query(Patient).filter(Patient.patient_number == patient_number, Patient.doctor_id == user.id).first()
            if existing_patient:
                # Skip this patient if already exists for this doctor
                continue
                
            new_patient = Patient(
                doctor_id=user.id,
                # clinic_id=clinic.id,
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
    try:
        # Clean column names and strip whitespace
        df.columns = df.columns.str.strip()
        
        # Pre-process all patient numbers and get patients in bulk
        df["Patient Number"] = df["Patient Number"].astype(str).str.strip().str.strip("'").str.strip('"')
        patient_numbers = df["Patient Number"].unique()
        patients = {
            p.patient_number: p for p in 
            db.query(Patient).filter(
                Patient.patient_number.in_(patient_numbers),
                # Patient.clinic_id == clinic.id,
                Patient.doctor_id == user.id
            ).all()
        }
        
        # Create appointment objects
        appointments = []
        
        # Convert date columns to datetime
        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
        df["Checked In At"] = pd.to_datetime(df["Checked In At"], errors='coerce')
        df["Checked Out At"] = pd.to_datetime(df["Checked Out At"], errors='coerce')

        # Clean text columns
        if "Notes" in df.columns:
            df["Notes"] = df["Notes"].astype(str).str.strip().str.strip("'").str.strip('"')
        if "Status" in df.columns:
            df["Status"] = df["Status"].astype(str).str.strip().str.strip("'").str.strip('"').str.lower()

        # Grouping by Patient Number, then sorting by Date
        grouped = df.sort_values(by=["Patient Number", "Date"]).groupby("Patient Number")

        # Creating JSON output with better formatting
        grouped_appointments = {}
        for patient, group in grouped:
            patient_key = str(patient).strip().strip("'").strip('"')
            appointments_list = clean_list_of_dicts(group.sort_values("Date").to_dict(orient="records"))
            grouped_appointments[patient_key] = appointments_list

        # Initialize progress tracking
        global total_rows, rows_processed, percentage_completed

        for k, v in grouped_appointments.items():
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            patient = patients.get(k)
            if patient:
                for appointment in v:
                    appointment_date = appointment.get("Date")
                    if pd.isna(appointment_date):
                        continue
                    
                    # Ensure status is a valid enum value
                    status_str = str(appointment.get("Status", "scheduled")).lower().strip()
                    try:
                        status = AppointmentStatus(status_str)
                    except ValueError:
                        status = AppointmentStatus.SCHEDULED
                        
                    new_appointment = Appointment(
                        patient_id=patient.id,
                        # clinic_id=clinic.id,
                        patient_number=patient.patient_number,
                        patient_name=patient.name,
                        appointment_date=appointment_date.date() if hasattr(appointment_date, 'date') else appointment_date,
                        start_time=appointment.get("Checked In At") if pd.notna(appointment.get("Checked In At")) else (appointment_date.date() if hasattr(appointment_date, 'date') else appointment_date),
                        end_time=appointment.get("Checked Out At") if pd.notna(appointment.get("Checked Out At")) else (appointment_date.date() if hasattr(appointment_date, 'date') else appointment_date),
                        checked_in_at=appointment.get("Checked In At") if pd.notna(appointment.get("Checked In At")) else None,
                        checked_out_at=appointment.get("Checked Out At") if pd.notna(appointment.get("Checked Out At")) else None,
                        status=status,
                        notes=str(appointment.get("Notes", "")).strip(),
                        doctor_id=user.id,
                        doctor_name=user.name,
                        share_on_email=False,
                        share_on_sms=False,
                        share_on_whatsapp=False,
                        send_reminder=False
                    )
                    appointments.append(new_appointment)
        
        # Bulk save all appointments
        if appointments:
            db.bulk_save_objects(appointments)
            db.commit()
            
        import_log.status = ImportStatus.COMPLETED
        db.commit()
        return True
    except Exception as e:
        print(f"Error during appointment processing: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during appointment processing: {str(e)}"})

async def process_treatment_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing treatment data")
    try:
        global total_rows, rows_processed, percentage_completed, total_progress
        # Clean column names and strip whitespace
        df.columns = df.columns.str.strip()
        
        # Pre-process all patient numbers and get patients in bulk
        df["Patient Number"] = df["Patient Number"].astype(str).str.strip().str.strip("'").str.strip('"')
        patient_numbers = df["Patient Number"].unique()
        patients = {
            p.patient_number: p for p in 
            db.query(Patient).filter(
                Patient.patient_number.in_(patient_numbers),
                # Patient.clinic_id == clinic.id
            ).all()
        }

        # Clean text columns
        text_columns = ["Treatment Name", "Tooth Number", "Treatment Notes", "DiscountType"]
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.strip("'").str.strip('"')

        # Convert date column to datetime
        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
        
        # Create a dictionary to store appointments by patient_id and date for quick lookup
        appointments_dict = {}
        
        # Get all potential appointment dates from the dataframe
        all_dates = []
        for d in df["Date"].dropna():
            if hasattr(d, 'date'):
                all_dates.append(d.date())
            elif isinstance(d, datetime.date):
                all_dates.append(d)
        
        # Fetch all appointments for these patients on these dates
        from sqlalchemy import func
        from datetime import timedelta
        
        all_appointments = db.query(Appointment).filter(
            Appointment.patient_id.in_([p.id for p in patients.values()]),
            # Appointment.clinic_id == clinic.id,
            func.date(Appointment.appointment_date).in_(all_dates)
        ).all()
        
        # Create lookup dictionary for appointments
        for appointment in all_appointments:
            # Ensure we're working with date objects consistently
            appt_date = appointment.appointment_date
            if hasattr(appt_date, 'date'):
                appt_date = appt_date.date()
            
            key = (appointment.patient_id, appt_date)
            appointments_dict[key] = appointment
        
        # Group by Patient Number
        grouped = df.groupby("Patient Number")
        
        treatments = []
        treatment_suggestions = set()
        
        # Create a dictionary to store all appointments by patient for finding nearest date
        patient_appointments = {}
        for key, appointment in appointments_dict.items():
            patient_id, date = key
            if patient_id not in patient_appointments:
                patient_appointments[patient_id] = []
            patient_appointments[patient_id].append((date, appointment))
        
        # Sort appointments by date for each patient
        for patient_id in patient_appointments:
            patient_appointments[patient_id].sort(key=lambda x: x[0])
        
        for patient_number, group in grouped:
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            patient_key = str(patient_number).strip()
            patient = patients.get(patient_key)
            
            if not patient:
                continue
                
            # Sort treatments by date for this patient
            patient_treatments = group.sort_values("Date").to_dict(orient="records")
            
            for treatment in patient_treatments:
                treatment_date = treatment.get("Date")
                treatment_name = treatment.get("Treatment Name")
                
                if pd.isna(treatment_date) or not treatment_name:
                    continue
                
                # Convert treatment_date to date object for lookup
                treatment_date_obj = None
                if hasattr(treatment_date, 'date'):
                    treatment_date_obj = treatment_date.date()
                elif isinstance(treatment_date, datetime.date):
                    treatment_date_obj = treatment_date
                else:
                    # Skip if we can't get a valid date
                    continue
                
                # Look up appointment in our dictionary
                appointment = appointments_dict.get((patient.id, treatment_date_obj))
                
                # If no appointment found, try to find the closest appointment within 1 day
                if not appointment and treatment_date_obj is not None:
                    # Check one day before and after
                    for delta in [-1, 1]:
                        adjacent_date = treatment_date_obj + timedelta(days=delta)
                        appointment = appointments_dict.get((patient.id, adjacent_date))
                        if appointment:
                            break
                
                # If still no appointment found, find the nearest appointment by date
                if not appointment and patient.id in patient_appointments and patient_appointments[patient.id]:
                    # Find the appointment with the closest date
                    nearest_appointment = min(
                        patient_appointments[patient.id], 
                        key=lambda x: abs((x[0] - treatment_date_obj).days)
                    )
                    appointment = nearest_appointment[1]
                
                # Clean and convert numeric fields
                try:
                    # Handle quantity
                    quantity = treatment.get("Quantity")
                    if quantity is not None:
                        if isinstance(quantity, str):
                            # Remove quotes and convert to integer
                            quantity = quantity.strip().strip("'").strip('"')
                            try:
                                quantity = int(quantity)
                            except ValueError:
                                quantity = 1
                        elif pd.isna(quantity):
                            quantity = 1
                        else:
                            try:
                                quantity = int(quantity)
                            except ValueError:
                                quantity = 1
                    else:
                        quantity = 1
                    
                    # Handle unit_cost
                    unit_cost = treatment.get("Treatment Cost")
                    if unit_cost is not None:
                        if isinstance(unit_cost, str):
                            unit_cost = unit_cost.strip().strip("'").strip('"')
                            try:
                                unit_cost = float(unit_cost)
                            except ValueError:
                                unit_cost = 0
                        elif pd.isna(unit_cost):
                            unit_cost = 0
                        else:
                            try:
                                unit_cost = float(unit_cost)
                            except ValueError:
                                unit_cost = 0
                    else:
                        unit_cost = 0
                    
                    # Handle amount
                    amount = treatment.get("Amount")
                    if amount is not None:
                        if isinstance(amount, str):
                            amount = amount.strip().strip("'").strip('"')
                            try:
                                amount = float(amount)
                            except ValueError:
                                amount = 0
                        elif pd.isna(amount):
                            amount = 0
                        else:
                            try:
                                amount = float(amount)
                            except ValueError:
                                amount = 0
                    else:
                        amount = 0
                    
                    # Handle discount
                    discount = treatment.get("Discount")
                    if discount is not None:
                        if isinstance(discount, str):
                            discount = discount.strip().strip("'").strip('"')
                            if discount:
                                try:
                                    discount = float(discount)
                                except ValueError:
                                    discount = 0
                            else:
                                discount = 0
                        elif pd.isna(discount):
                            discount = 0
                        else:
                            try:
                                discount = float(discount)
                            except ValueError:
                                discount = 0
                    else:
                        discount = 0
                    
                    # Handle discount_type
                    discount_type = treatment.get("DiscountType")
                    if discount_type is not None:
                        if isinstance(discount_type, str):
                            discount_type = discount_type.strip().strip("'").strip('"')
                            if not discount_type or discount_type.upper() not in ["PERCENT", "AMOUNT"]:
                                discount_type = "PERCENT"
                        else:
                            discount_type = "PERCENT"
                    else:
                        discount_type = "PERCENT"
                    
                    # Handle tooth_number
                    tooth_number = treatment.get("Tooth Number")
                    if tooth_number is not None:
                        if isinstance(tooth_number, str):
                            tooth_number = tooth_number.strip().strip("'").strip('"')
                        elif pd.isna(tooth_number):
                            tooth_number = None
                    
                    # Handle treatment_notes
                    treatment_notes = treatment.get("Treatment Notes")
                    if treatment_notes is not None:
                        if isinstance(treatment_notes, str):
                            treatment_notes = treatment_notes.strip().strip("'").strip('"')
                        elif pd.isna(treatment_notes):
                            treatment_notes = None
                    
                    # Clean treatment name
                    if isinstance(treatment_name, str):
                        treatment_name = treatment_name.strip().strip("'").strip('"')
                    
                    # Create treatment record if we have an appointment
                    if appointment:
                        new_treatment = Treatment(
                            patient_id=patient.id,
                            appointment_id=appointment.id,
                            # clinic_id=clinic.id,
                            treatment_date=treatment_date,
                            treatment_name=treatment_name,
                            tooth_number=tooth_number,
                            treatment_notes=treatment_notes,
                            quantity=quantity,
                            unit_cost=unit_cost,
                            amount=amount,
                            discount=discount,
                            discount_type=discount_type,
                            doctor_id=user.id
                        )
                        treatments.append(new_treatment)
                        
                        # Add treatment name to suggestions set
                        if treatment_name:
                            treatment_suggestions.add(treatment_name)
                except Exception as e:
                    print(f"Error processing treatment: {str(e)}")
                    continue
        
        # Bulk save all treatments
        if treatments:
            db.bulk_save_objects(treatments)
        
        # Add treatment suggestions that don't already exist
        existing_suggestions = {
            s.treatment_name for s in 
            db.query(TreatmentNameSuggestion.treatment_name)
            .all()
        }
        new_suggestions = []
        
        for treatment_name in treatment_suggestions:
            if treatment_name not in existing_suggestions:
                new_suggestions.append(TreatmentNameSuggestion(
                    treatment_name=treatment_name,
                ))
        
        if new_suggestions:
            db.bulk_save_objects(new_suggestions)
        
        print(f"Processed {len(treatments)} treatments.")
        
        db.commit()
        import_log.status = ImportStatus.COMPLETED
        db.commit()
        return True
    except Exception as e:
        print(f"Error during treatment processing: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during treatment processing: {str(e)}"})

def normalize_string(s: str) -> str:
    return " ".join(s.split()).lower()

async def process_clinical_note_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing clinical note data")
    try:
        global total_rows, rows_processed, percentage_completed, total_progress
        # Clean and prepare data
        df.columns = df.columns.str.strip()
        df["Patient Number"] = df["Patient Number"].astype(str).str.strip("'")
        df["Patient Name"] = df["Patient Name"].astype(str).str.strip("'")
        df["Doctor"] = df["Doctor"].astype(str).str.strip("'")
        df["Type"] = df["Type"].astype(str).str.strip("'")
        df["Description"] = df["Description"].astype(str).str.strip("'").str.strip('"')
        df["Date"] = pd.to_datetime(df["Date"].astype(str).str.strip("'"), errors='coerce')
        
        # Pre-process all patient numbers and get patients in bulk
        patient_numbers = df["Patient Number"].unique()
        patients = {
            p.patient_number: p for p in 
            db.query(Patient).filter(
                Patient.patient_number.in_(patient_numbers),
                # Patient.clinic_id == clinic.id
            ).all()
        }
        
        # Get all appointments for these patients to match with dates
        patient_ids = [p.id for p in patients.values()]
        appointments_by_patient = {}
        
        if patient_ids:
            all_appointments = db.query(Appointment).filter(
                Appointment.patient_id.in_(patient_ids),
                # Appointment.clinic_id == clinic.id
            ).all()
            
            # Group appointments by patient_id for faster lookup
            for appt in all_appointments:
                if appt.patient_id not in appointments_by_patient:
                    appointments_by_patient[appt.patient_id] = []
                
                appointments_by_patient[appt.patient_id].append(appt)
        
        # Track statistics
        clinical_notes_created = 0
        skipped_notes = 0
        
        # Group by Patient Number and Date
        grouped = df.groupby(["Patient Number", "Date"])
        
        for (patient_number, note_date), group in grouped:
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            patient = patients.get(patient_number)
            
            if not patient or pd.isna(note_date):
                skipped_notes += len(group)
                continue
            
            # Convert date to datetime object for comparison
            note_date_obj = note_date.date() if hasattr(note_date, 'date') else note_date
            
            # Find appointment for this patient with the nearest date
            appointment = None
            if patient.id in appointments_by_patient and appointments_by_patient[patient.id]:
                # Get all appointments for this patient
                patient_appointments = appointments_by_patient[patient.id]
                
                # Find the appointment with the closest date
                closest_appointment = None
                min_days_diff = float('inf')
                
                for appt in patient_appointments:
                    appt_date = appt.appointment_date.date() if hasattr(appt.appointment_date, 'date') else appt.appointment_date
                    days_diff = abs((note_date_obj - appt_date).days)
                    
                    if days_diff < min_days_diff:
                        min_days_diff = days_diff
                        closest_appointment = appt
                
                appointment = closest_appointment
            
            # Create clinical note
            clinical_note = ClinicalNote(
                patient_id=patient.id,
                date=note_date,
                appointment_id=appointment.id if appointment else None,
                doctor_id=user.id,
                # clinic_id=clinic.id
            )
            db.add(clinical_note)
            db.flush()  # Get ID without committing transaction
            clinical_notes_created += 1
            
            # Process each row in this group
            for _, row in group.iterrows():
                note_type = row["Type"].lower()
                description = row["Description"]
                
                if not description:
                    continue
                
                # Clean the description before saving
                description = description.strip()
                
                if "complaint" in note_type:
                    complaint = Complaint(
                        clinical_note_id=clinical_note.id,
                        complaint=description
                    )
                    db.add(complaint)
                    
                    # Add to suggestions - clean before normalizing
                    normalized_complaint = normalize_string(description)
                    existing = db.query(ComplaintSuggestion).filter(
                        ComplaintSuggestion.complaint == normalized_complaint
                    ).first()
                    if not existing:
                        db.add(ComplaintSuggestion(complaint=normalized_complaint))
                    
                elif "diagnos" in note_type:
                    diagnosis = Diagnosis(
                        clinical_note_id=clinical_note.id,
                        diagnosis=description
                    )
                    db.add(diagnosis)
                    
                    # Clean before normalizing
                    normalized_diagnosis = normalize_string(description)
                    existing = db.query(DiagnosisSuggestion).filter(
                        DiagnosisSuggestion.diagnosis == normalized_diagnosis
                    ).first()
                    if not existing:
                        db.add(DiagnosisSuggestion(diagnosis=normalized_diagnosis))
                    
                elif "vital" in note_type:
                    vital_sign = VitalSign(
                        clinical_note_id=clinical_note.id,
                        vital_sign=description
                    )
                    db.add(vital_sign)
                    
                    # Clean before normalizing
                    normalized_vital_sign = normalize_string(description)
                    existing = db.query(VitalSignSuggestion).filter(
                        VitalSignSuggestion.vital_sign == normalized_vital_sign
                    ).first()
                    if not existing:
                        db.add(VitalSignSuggestion(vital_sign=normalized_vital_sign))
                
                elif "observation" in note_type:
                    observation = Observation(
                        clinical_note_id=clinical_note.id,
                        observation=description
                    )
                    db.add(observation)
                    
                    # Clean before normalizing
                    normalized_observation = normalize_string(description)
                    existing = db.query(ObservationSuggestion).filter(
                        ObservationSuggestion.observation == normalized_observation
                    ).first()
                    if not existing:
                        db.add(ObservationSuggestion(observation=normalized_observation))
                    
                elif "investigation" in note_type:
                    # Handle investigation type notes
                    investigation = Investigation(
                        clinical_note_id=clinical_note.id,
                        investigation=description
                    )
                    db.add(investigation)
                    
                    # Clean before normalizing
                    normalized_investigation = normalize_string(description)
                    existing = db.query(InvestigationSuggestion).filter(
                        InvestigationSuggestion.investigation == normalized_investigation
                    ).first()
                    if not existing:
                        db.add(InvestigationSuggestion(investigation=normalized_investigation))
                    
                elif "note" in note_type or "treatment" in note_type:
                    note = Notes(
                        clinical_note_id=clinical_note.id,
                        note=description
                    )
                    db.add(note)
        
        # Commit all changes
        db.commit()
        
        # Update import log status
        import_log.status = ImportStatus.COMPLETED
        db.commit()
        
        print(f"Clinical note data processed successfully. Created {clinical_notes_created} clinical notes. Skipped {skipped_notes} entries.")
        return True
        
    except Exception as e:
        print(f"Error during clinical notes processing: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during clinical notes processing: {str(e)}"})

async def process_treatment_plan_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing treatment plan data")
    try:
        global total_rows, rows_processed, percentage_completed, total_progress
        # Clean and prepare data
        df.columns = df.columns.str.strip()
        
        # Print column names for debugging
        print(f"Available columns: {df.columns.tolist()}")
        
        # Handle required columns with error checking
        df["Patient Number"] = df["Patient Number"].astype(str).str.strip("'")
        
        # Convert date with error handling
        df["Date"] = pd.to_datetime(df["Date"].astype(str).str.strip("'"), errors='coerce')
        
        # Dynamically handle cost column - check for different possible column names
        cost_column = None
        for possible_name in ["UnitCost", "Treatment Cost", "Cost", "Unit Cost", "Price"]:
            if possible_name in df.columns:
                cost_column = possible_name
                break
                
        if cost_column:
            df["UnitCost"] = pd.to_numeric(df[cost_column].astype(str).str.strip("'"), errors="coerce").fillna(0)
        else:
            # If no cost column exists, add a default UnitCost column
            df["UnitCost"] = 0
            print("Warning: No cost column found in the data. Using 0 as default.")
            
        # Handle Treatment Name column with similar flexibility
        treatment_name_column = None
        for possible_name in ["Treatment Name", "Treatment", "Procedure", "Service"]:
            if possible_name in df.columns:
                treatment_name_column = possible_name
                break
                
        if treatment_name_column:
            df["Treatment Name"] = df[treatment_name_column].astype(str).str.strip("'")
        else:
            df["Treatment Name"] = "Unknown Treatment"
            print("Warning: No treatment name column found. Using 'Unknown Treatment' as default.")
            
        # Handle other numeric columns
        for col, default in [
            ("Quantity", 1),
            ("Discount", 0),
            ("Amount", 0)
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.strip("'"), errors="coerce").fillna(default)
            else:
                df[col] = default
        
        # Handle optional text columns
        for col, default in [
            ("Tooth Number", ""),
            ("DiscountType", ""),
            ("Treatment Notes", "")
        ]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip("'").str.strip('"').str.strip()
            else:
                df[col] = default
        
        # Pre-process all patient numbers and get patients in bulk
        patient_numbers = df["Patient Number"].unique()
        patients = {
            p.patient_number: p for p in 
            db.query(Patient).filter(
                Patient.patient_number.in_(patient_numbers),
                # Patient.clinic_id == clinic.id
            ).all()
        }
    
        
        # Get all appointments for these patients to match with dates
        patient_ids = [p.id for p in patients.values()]
        appointments_by_patient = {}
        
        if patient_ids:
            all_appointments = db.query(Appointment).filter(
                Appointment.patient_id.in_(patient_ids),
                # Appointment.clinic_id == clinic.id
            ).all()
            
            
            # Group appointments by patient_id and date for faster lookup
            for appt in all_appointments:
                if appt.patient_id not in appointments_by_patient:
                    appointments_by_patient[appt.patient_id] = {}
                
                appt_date_str = appt.appointment_date.strftime('%Y-%m-%d')
                if appt_date_str not in appointments_by_patient[appt.patient_id]:
                    appointments_by_patient[appt.patient_id][appt_date_str] = []
                
                appointments_by_patient[appt.patient_id][appt_date_str].append(appt)
        
        # Track statistics
        plans_created = 0
        treatments_created = 0
        skipped_entries = 0
        treatment_suggestions = set()
        
        # Group by Patient Number and Date
        grouped = df.groupby(["Patient Number", "Date"])
        
        for (patient_number, treatment_date), group in grouped:
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            try:
                patient = patients.get(patient_number)
                
                if not patient:
                    skipped_entries += len(group)
                    continue
                
                if pd.isna(treatment_date):
                    skipped_entries += len(group)
                    continue
                    
                date_str = treatment_date.strftime('%Y-%m-%d')
                appointment = None
                
                # Find matching appointment
                if patient.id in appointments_by_patient and date_str in appointments_by_patient[patient.id]:
                    # Use the first appointment for this date
                    appointment = appointments_by_patient[patient.id][date_str][0]
                else:
                    # Find appointment with nearest date if no exact match
                    if patient.id in appointments_by_patient and appointments_by_patient[patient.id]:
                        # Get all appointment dates for this patient
                        all_dates = []
                        for date_key, appts in appointments_by_patient[patient.id].items():
                            appt_date = datetime.strptime(date_key, '%Y-%m-%d').date()
                            all_dates.append((appt_date, appts[0]))  # Store date and first appointment
                        
                        if all_dates:
                            # Find appointment with closest date
                            closest_date = min(all_dates, key=lambda x: abs((treatment_date.date() - x[0]).days))
                            appointment = closest_date[1]
                
                # Create treatment plan
                treatment_plan = TreatmentPlan(
                    patient_id=patient.id,
                    doctor_id=user.id,
                    date=treatment_date,
                    appointment_id=appointment.id if appointment else None,
                    # clinic_id=clinic.id
                )
                db.add(treatment_plan)
                db.flush()  # Get ID without committing transaction
                
                plans_created += 1
                
                # Process each treatment in the group
                for _, row in group.iterrows():
                    try:
                        # Clean data before using
                        treatment_name = str(row.get("Treatment Name", "Unknown Treatment")).strip()
                        unit_cost = float(row.get("UnitCost", 0.0))
                        quantity = int(row.get("Quantity", 1))
                        discount = float(row.get("Discount", 0))
                        discount_type = str(row.get("DiscountType", "")).strip()
                        tooth_number = str(row.get("Tooth Number", "")).strip()
                        treatment_notes = str(row.get("Treatment Notes", "")).strip()
                        
                        # Calculate amount with discount applied
                        if discount_type and discount_type.upper() == "PERCENT":
                            amount = unit_cost * quantity * (1 - discount / 100)
                        else:
                            # If Amount is provided, use it, otherwise calculate
                            amount = float(row.get("Amount", unit_cost * quantity))
                        
                        treatment = Treatment(
                            treatment_plan_id=treatment_plan.id,
                            patient_id=patient.id,
                            doctor_id=user.id,
                            # clinic_id=clinic.id,
                            appointment_id=appointment.id if appointment else None,
                            treatment_date=treatment_date,
                            treatment_name=treatment_name[:255] if treatment_name else "Unnamed Treatment",
                            unit_cost=unit_cost,
                            quantity=quantity,
                            discount=discount,
                            discount_type=discount_type[:50] if discount_type else None,
                            amount=amount,
                            treatment_notes=treatment_notes,
                            tooth_number=tooth_number
                        )
                        
                        db.add(treatment)
                        treatments_created += 1
                        
                        # Add treatment name to suggestions set
                        if treatment_name and treatment_name != "Unknown Treatment":
                            treatment_suggestions.add(treatment_name)
                            
                    except Exception as e:
                        print(f"Error processing individual treatment: {str(e)}")
                        continue
            except Exception as e:
                print(f"Error processing group for patient {patient_number} on {date_str}: {str(e)}")
                continue
        
        # Add treatment name suggestions that don't already exist
        existing_suggestions = {s.treatment_name for s in db.query(TreatmentNameSuggestion.treatment_name).all()}
        new_suggestions = []
        
        for treatment_name in treatment_suggestions:
            if treatment_name and treatment_name not in existing_suggestions:
                new_suggestions.append(TreatmentNameSuggestion(treatment_name=treatment_name))
        
        if new_suggestions:
            db.bulk_save_objects(new_suggestions)
        
        # Commit all changes
        db.commit()
        
        # Update import log status
        import_log.status = ImportStatus.COMPLETED
        db.commit()
        
        print(f"Treatment plan data processed successfully. Created {plans_created} plans with {treatments_created} treatments. Skipped {skipped_entries} entries.")
        return True
        
    except Exception as e:
        print(f"Error during treatment plan processing: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during treatment plan processing: {str(e)}"})

async def process_expense_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing expense data")
    
    try:
        global total_rows, rows_processed, percentage_completed, total_progress
        # Clean and prepare data
        df.columns = df.columns.str.strip()
        
        # Helper function for data cleaning
        def clean_string(value, max_length=None):
            if pd.isna(value):
                return ""
            result = str(value).strip().strip("'").strip('"')
            if max_length:
                result = result[:max_length]
            return result
        
        def safe_float_convert(value):
            try:
                cleaned = clean_string(value)
                if not cleaned:
                    return 0.0
                return float(cleaned)
            except (ValueError, TypeError):
                return 0.0
        
        def safe_date_convert(value):
            if pd.isna(value):
                return None
            try:
                return pd.to_datetime(value, errors='coerce')
            except:
                return None
        
        # Clean and convert data types
        df["Date"] = df["Date"].apply(safe_date_convert)
        df["Expense Type"] = df["Expense Type"].apply(lambda x: clean_string(x, 255))
        df["Description"] = df["Description"].apply(clean_string)
        df["Amount"] = df["Amount"].apply(safe_float_convert)
        df["Vendor Name"] = df["Vendor Name"].apply(lambda x: clean_string(x, 255))

        expenses = []
        # Build list of expense objects
        for _, row in df.iterrows():
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            expense = Expense(
                date=row["Date"],
                doctor_id=user.id,
                # clinic_id=clinic.id,
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
            import_log.status = ImportStatus.COMPLETED
            db.commit()
            
        print(f"Expense data processed successfully. Created {len(expenses)} expense records.")
        return True
            
    except Exception as e:
        print(f"Error processing expenses: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error processing expenses: {str(e)}"})

async def process_payment_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing payment data")
    
    try:
        global total_rows, rows_processed, percentage_completed, total_progress
        # Clean and prepare data
        df.columns = df.columns.str.strip()
        
        # Helper functions for data cleaning
        def clean_string(value, max_length=None):
            if pd.isna(value):
                return ""
            result = str(value).strip().strip("'").strip('"')
            if max_length:
                result = result[:max_length]
            return result
        
        def safe_float_convert(value):
            try:
                cleaned = clean_string(value)
                if not cleaned:
                    return 0.0
                return float(cleaned)
            except (ValueError, TypeError):
                return 0.0
        
        def safe_bool_convert(value):
            cleaned = clean_string(value)
            return cleaned == "1" or cleaned.lower() == "true"
        
        # Clean and convert data types
        df["Date"] = pd.to_datetime(df["Date"].apply(clean_string), errors='coerce')
        df["Patient Number"] = df["Patient Number"].apply(lambda x: clean_string(x, 50))
        df["Patient Name"] = df["Patient Name"].apply(lambda x: clean_string(x, 255))
        df["Receipt Number"] = df["Receipt Number"].apply(lambda x: clean_string(x, 50))
        df["Treatment name"] = df["Treatment name"].apply(lambda x: clean_string(x, 255))
        df["Amount Paid"] = df["Amount Paid"].apply(safe_float_convert)
        df["Invoice Number"] = df["Invoice Number"].apply(lambda x: clean_string(x, 50))
        df["Payment Mode"] = df["Payment Mode"].apply(lambda x: clean_string(x, 50))
        df["Card Number"] = df["Card Number"].apply(lambda x: clean_string(x, 50))
        df["Cancelled"] = df["Cancelled"].apply(safe_bool_convert)
        df["Refunded amount"] = df["Refunded amount"].apply(safe_float_convert)
        df["Notes"] = df["Notes"].apply(lambda x: clean_string(x, 1000)) if "Notes" in df.columns else ""
        
        # Remove rows with missing critical data
        df = df.dropna(subset=["Patient Number", "Date"])
        
        # Get all unique patient numbers
        patient_numbers = df["Patient Number"].unique()
        
        # Bulk fetch all patients in one query
        patients = {
            p.patient_number: p for p in 
            db.query(Patient).filter(
                Patient.patient_number.in_(patient_numbers),
                # Patient.clinic_id == clinic.id
            ).all()
        }
        
        # Get all patient IDs
        patient_ids = [p.id for p in patients.values()]
        
        # Fetch all appointments for these patients
        appointments_by_patient = {}
        if patient_ids:
            all_appointments = db.query(Appointment).filter(
                Appointment.patient_id.in_(patient_ids),
                # Appointment.clinic_id == clinic.id
            ).all()
            
            # Group appointments by patient_id for faster lookup
            for appt in all_appointments:
                if appt.patient_id not in appointments_by_patient:
                    appointments_by_patient[appt.patient_id] = []
                appointments_by_patient[appt.patient_id].append(appt)
        
        # Fetch all invoices to link them to payments
        invoices_by_number = {}
        invoice_numbers = df["Invoice Number"].dropna().unique()
        if len(invoice_numbers) > 0:
            all_invoices = db.query(Invoice).filter(
                Invoice.invoice_number.in_(invoice_numbers),
                # Invoice.clinic_id == clinic.id
            ).all()
            
            for invoice in all_invoices:
                invoices_by_number[invoice.invoice_number] = invoice
        
        # Group by Patient Number, Date, and Receipt Number (to handle multiple treatments in one receipt)
        grouped = df.groupby(["Patient Number", "Date", "Receipt Number"])
        
        payments = []
        processed_count = 0
        skipped_count = 0
        
        for (patient_number, payment_date, receipt_number), group in grouped:
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            # Skip if no patient number or date
            if not patient_number or pd.isna(payment_date):
                skipped_count += 1
                continue
            
            patient = patients.get(patient_number)
            if not patient:
                print(f"Patient with number {patient_number} not found, skipping payment")
                skipped_count += 1
                continue
            
            # Find appointment for this patient with nearest date
            appointment = None
            if patient.id in appointments_by_patient and appointments_by_patient[patient.id]:
                # Convert payment date to datetime.date for comparison
                payment_date_only = payment_date.date() if hasattr(payment_date, 'date') else payment_date
                
                # Find appointment with nearest date
                nearest_appointment = None
                min_days_diff = float('inf')
                
                for appt in appointments_by_patient[patient.id]:
                    appt_date = appt.appointment_date.date() if hasattr(appt.appointment_date, 'date') else appt.appointment_date
                    days_diff = abs((payment_date_only - appt_date).days)
                    
                    if days_diff < min_days_diff:
                        min_days_diff = days_diff
                        nearest_appointment = appt
                
                appointment = nearest_appointment
            
            # Calculate total amount for this group
            total_amount = group["Amount Paid"].sum()
            
            # Get patient name from first row
            patient_name = group.iloc[0]["Patient Name"]
            
            # Get payment mode from first row
            payment_mode = group.iloc[0]["Payment Mode"]
            
            # Check if any row in the group is cancelled
            is_cancelled = any(group["Cancelled"])
            
            # Get treatment names as a combined string
            treatment_names = ", ".join(filter(None, group["Treatment name"].unique()))
            
            # Get invoice number from first row (assuming same invoice for grouped items)
            invoice_number = group.iloc[0]["Invoice Number"]
            
            # Link to invoice if it exists
            invoice_id = None
            if invoice_number and invoice_number in invoices_by_number:
                invoice_id = invoices_by_number[invoice_number].id
            
            # Get refund information
            refunded_amount = group["Refunded amount"].sum() if "Refunded amount" in group.columns else 0.0
            is_refund = any(group["Refund"]) if "Refund" in group.columns else False
            refund_receipt_number = next((row["Refund Receipt Number"] for _, row in group.iterrows() 
                                         if "Refund Receipt Number" in row and row["Refund Receipt Number"]), "")
            
            # Combine notes if available
            notes = "; ".join(filter(None, group["Notes"].unique())) if "Notes" in group.columns else ""
            
            # Create payment record
            payment = Payment(
                date=payment_date,
                doctor_id=user.id,
                # clinic_id=clinic.id,
                patient_id=patient.id,
                appointment_id=appointment.id if appointment else None,
                invoice_id=invoice_id,
                patient_number=patient_number,
                patient_name=patient_name,
                receipt_number=receipt_number,
                treatment_name=treatment_names,
                amount_paid=total_amount,
                invoice_number=invoice_number,
                notes=notes,
                payment_mode=payment_mode,
                refund=is_refund,
                refund_receipt_number=refund_receipt_number,
                refunded_amount=refunded_amount,
                cancelled=is_cancelled
            )
            payments.append(payment)
            processed_count += 1
        
        # Bulk insert all payments
        if payments:
            db.bulk_save_objects(payments)
            db.commit()
            import_log.status = ImportStatus.COMPLETED
            db.commit()
            
        print(f"Payment data processed successfully. Created {processed_count} payment records. Skipped {skipped_count} entries.")
        return True
    except Exception as e:
        print(f"Error processing payments: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error processing payments: {str(e)}"})

async def process_invoice_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing invoice data")
    
    try:
        global total_rows, rows_processed, percentage_completed, total_progress
        # Clean and prepare data
        df.columns = df.columns.str.strip()
        
        # Helper functions for data cleaning
        def clean_string(value, max_length=None):
            if pd.isna(value):
                return ""
            result = str(value).strip().strip("'").strip('"')
            if max_length:
                result = result[:max_length]
            return result
        
        def safe_parse_number(value, convert_func, default=None):
            if pd.isna(value):
                return default
            try:
                val_str = str(value).strip("'")
                return convert_func(val_str)
            except (ValueError, TypeError):
                return default
        
        # Convert and clean data
        df["Date"] = pd.to_datetime(df["Date"].apply(clean_string), errors='coerce')
        df["Patient Number"] = df["Patient Number"].apply(lambda x: clean_string(x, 255))
        df["Patient Name"] = df["Patient Name"].apply(lambda x: clean_string(x, 255))
        df["Doctor Name"] = df["Doctor Name"].apply(lambda x: clean_string(x, 255))
        df["Invoice Number"] = df["Invoice Number"].apply(lambda x: clean_string(x, 255))
        df["Treatment Name"] = df["Treatment Name"].apply(lambda x: clean_string(x, 255))
        df["Cancelled"] = df["Cancelled"].fillna(False).astype(bool)
        df["Notes"] = df["Notes"].apply(lambda x: clean_string(x)) if "Notes" in df.columns else ""
        df["Description"] = df["Description"].apply(lambda x: clean_string(x)) if "Description" in df.columns else ""
        
        # Convert numeric columns
        df["Unit Cost"] = df["Unit Cost"].apply(lambda x: safe_parse_number(x, float, 0.0))
        df["Quantity"] = df["Quantity"].apply(lambda x: safe_parse_number(x, int, 1))
        df["Discount"] = df["Discount"].apply(lambda x: safe_parse_number(x, float, 0.0))
        df["Tax Percent"] = df["Tax Percent"].apply(lambda x: safe_parse_number(x, float, 0.0))
        df["Invoice Level Tax Discount"] = df["Invoice Level Tax Discount"].apply(lambda x: safe_parse_number(x, float, 0.0))
        df["DiscountType"] = df["DiscountType"].apply(lambda x: clean_string(x, 255)) if "DiscountType" in df.columns else ""
        df["Type"] = df["Type"].apply(lambda x: clean_string(x, 255)) if "Type" in df.columns else ""
        df["Tax name"] = df["Tax name"].apply(lambda x: clean_string(x, 255)) if "Tax name" in df.columns else ""
        
        # Get all unique patient numbers from the dataframe
        patient_numbers = df["Patient Number"].unique()
        
        # Bulk fetch all patients in one query
        patients = {
            p.patient_number: p for p in 
            db.query(Patient).filter(
                Patient.patient_number.in_(patient_numbers),
                # Patient.clinic_id == clinic.id
            ).all()
        }
        
        # Get all appointments for these patients
        patient_ids = [p.id for p in patients.values()]
        all_appointments_by_patient = {}
        
        if patient_ids:
            all_appointments = db.query(Appointment).filter(
                Appointment.patient_id.in_(patient_ids),
                # Appointment.clinic_id == clinic.id
            ).all()
            
            # Group appointments by patient_id for faster lookup
            for appt in all_appointments:
                if appt.patient_id not in all_appointments_by_patient:
                    all_appointments_by_patient[appt.patient_id] = []
                all_appointments_by_patient[appt.patient_id].append(appt)
        
        # Get all existing payments to link with invoices
        all_payments = db.query(Payment).all()
        payments_by_invoice_number = {
            p.invoice_number: p for p in all_payments if p.invoice_number
        }
        
        # Group by Patient Number, Date, and Invoice Number
        invoice_groups = df.groupby(["Patient Number", "Date", "Invoice Number"])
        
        invoices_created = 0
        items_created = 0
        skipped_invoices = 0
        for (patient_number, invoice_date, invoice_number), group in invoice_groups:
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            # Skip if date is invalid
            if pd.isna(invoice_date):
                skipped_invoices += 1
                continue
                
            # Get patient
            patient = patients.get(patient_number)
            if not patient:
                print(f"Patient with number {patient_number} not found, skipping invoice {invoice_number}")
                skipped_invoices += 1
                continue
            
            # Find appointment for this patient - get the one with nearest date
            appointment = None
            if patient.id in all_appointments_by_patient and all_appointments_by_patient[patient.id]:
                # Find appointment with nearest date
                patient_appointments = all_appointments_by_patient[patient.id]
                
                # Calculate time difference between invoice date and each appointment date
                nearest_appointment = None
                min_time_diff = float('inf')
                
                for appt in patient_appointments:
                    time_diff = abs((invoice_date - appt.appointment_date.replace(tzinfo=None)).total_seconds())
                    if time_diff < min_time_diff:
                        min_time_diff = time_diff
                        nearest_appointment = appt
                
                appointment = nearest_appointment
            
            # Get payment if it exists
            payment = payments_by_invoice_number.get(invoice_number)
            
            # Check if any item in the group is cancelled
            is_cancelled = any(group["Cancelled"])
            
            # Get the first row for basic invoice info
            first_row = group.iloc[0]
            
            # Create invoice
            invoice = Invoice(
                date=invoice_date,
                doctor_id=user.id,
                # clinic_id=clinic.id,
                patient_id=patient.id,
                appointment_id=appointment.id if appointment else None,
                payment_id=payment.id if payment else None,
                patient_number=patient_number,
                patient_name=first_row["Patient Name"],
                doctor_name=first_row["Doctor Name"],
                invoice_number=invoice_number,
                cancelled=is_cancelled,
                notes=str(first_row.get("Notes", "")),
                description=str(first_row.get("Description", "")),
                total_amount=0.0  # Initialize with zero, will update later
            )
            
            db.add(invoice)
            db.flush()  # Flush to get the invoice ID
            invoices_created += 1
            
            # Process each item in the group
            total_invoice_amount = 0.0
            
            for _, row in group.iterrows():
                # Parse discount type
                discount_type = row.get("DiscountType", "").upper() if pd.notna(row.get("DiscountType")) else None
                
                # Get values
                unit_cost = safe_parse_number(row["Unit Cost"], float, 0.0)
                quantity = safe_parse_number(row["Quantity"], int, 1)
                discount = safe_parse_number(row["Discount"], float, 0.0)
                tax_percent = safe_parse_number(row.get("Tax Percent"), float, 0.0)
                
                # Create invoice item
                invoice_item = InvoiceItem(
                    invoice_id=invoice.id,
                    treatment_name=row["Treatment Name"],
                    unit_cost=unit_cost,
                    quantity=quantity,
                    discount=discount,
                    discount_type=discount_type,
                    type=str(row.get("Type", "")),
                    invoice_level_tax_discount=safe_parse_number(row.get("Invoice Level Tax Discount"), float, 0.0),
                    tax_name=str(row.get("Tax name", "")),
                    tax_percent=tax_percent
                )
                
                db.add(invoice_item)
                items_created += 1
                
                # Calculate item total
                item_total = unit_cost * quantity  # Base cost
                
                # Apply discount
                if discount:
                    if discount_type == "PERCENTAGE" or discount_type == "PERCENT":
                        item_total -= (item_total * discount / 100)
                    elif discount_type == "FIXED" or discount_type == "NUMBER":
                        item_total -= discount
                
                # Apply tax
                if tax_percent:
                    tax_amount = (item_total * tax_percent / 100)
                    item_total += tax_amount
                
                # Add to invoice total
                total_invoice_amount += item_total
            
            # Update invoice total
            invoice.total_amount = total_invoice_amount
        
        # Commit all changes at once
        print(f"Number of invoices to process: {invoices_created}")
        if invoices_created > 0:
            db.commit()
            import_log.status = ImportStatus.COMPLETED
            db.commit()
            return JSONResponse(
                status_code=200, 
                content={
                    "message": f"Successfully processed {invoices_created} invoices with {items_created} items. Skipped {skipped_invoices} invoices."
                }
            )
        else:
            return JSONResponse(status_code=200, content={"message": "No invoices to process"})
            
    except Exception as e:
        print(f"Error during invoice processing: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during invoice processing: {str(e)}"})

async def process_procedure_catalog_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing procedure catalog data")
    
    try:
        global total_rows, rows_processed, percentage_completed, total_progress
        # Clean and validate data according to model requirements
        df['treatment_cost'] = df['Treatment Cost'].fillna('0').astype(str).str.strip().str.strip("'")
        df['treatment_name'] = df['Treatment Name'].fillna('').astype(str).str.strip().str.strip("'").str[:255]
        df['treatment_notes'] = df['Treatment Notes'].fillna('').astype(str).str.strip()
        df['locale'] = df['Locale'].fillna('en').astype(str).str.strip().str.strip("'").str[:50]
        
        # Filter out rows with empty treatment names
        df = df[df['treatment_name'].str.len() > 0]
        
        # Create all ProcedureCatalog objects in memory
        procedures = []
        treatment_suggestions = set()
        
        for _, row in df.iterrows():
            # Update progress
            update_progress(1, total_rows, import_log, db)
            
            # Ensure treatment_name is not empty and properly formatted
            if not row['treatment_name']:
                continue

                
            # Create procedure catalog entry
            procedure = ProcedureCatalog(
                user_id=user.id,
                # clinic_id=clinic.id,  # Use the passed in clinic's ID
                treatment_name=row['treatment_name'],
                treatment_cost=row['treatment_cost'],
                treatment_notes=row['treatment_notes'],
                locale=row['locale'] if row['locale'] else 'en'
            )
            procedures.append(procedure)
            
            # Add to treatment suggestions set
            treatment_suggestions.add(row['treatment_name'])
        
        # Bulk insert all procedure records
        if procedures:
            db.bulk_save_objects(procedures)
            
        # Get existing treatment name suggestions to avoid duplicates
        existing_suggestions = {s.treatment_name for s in db.query(TreatmentNameSuggestion.treatment_name).all()}
        
        # Create new suggestion objects for names that don't exist yet
        new_suggestions = []
        for treatment_name in treatment_suggestions:
            if treatment_name not in existing_suggestions:
                new_suggestions.append(TreatmentNameSuggestion(treatment_name=treatment_name))
        
        # Bulk insert new treatment name suggestions
        if new_suggestions:
            db.bulk_save_objects(new_suggestions)
            
        # Commit all changes
        db.commit()
        
        import_log.status = ImportStatus.COMPLETED
        db.commit()
        
        return JSONResponse(
            status_code=200,
            content={"message": f"Successfully processed {len(procedures)} procedure catalog entries"}
        )
            
    except Exception as e:
        print(f"Error processing procedure catalog data: {str(e)}")
        import traceback
        traceback.print_exc()
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
        # clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
        if not import_log:
            print(f"Import log with id {import_log_id} not found")
            return
        if not user:
            print(f"User with id {user_id} not found")
            return
        # if not clinic:
        #     print(f"Clinic with id {clinic_id} not found")
        #     return

        file_ext = os.path.splitext(file_path)[1].lower()
        print(f"File extension: {file_ext}")
        
        # Extract if zip file
        if file_ext == '.zip':
            try:
                print("Extracting zip file...")
                import_log.current_stage = "Extracting ZIP file"
                db.commit()
                
                with zipfile.ZipFile(file_path, "r") as zip_ref:
                    zip_ref.extractall(f"uploads/imports/{uuid}")
                print("Zip file extracted successfully")
                
                db.commit()
            except Exception as e:
                print(f"Error extracting zip file: {str(e)}")
                import_log.status = ImportStatus.FAILED
                import_log.error_message = f"Failed to extract ZIP: {str(e)}"
                db.commit()
                return

        # Update status to processing
        import_log.status = ImportStatus.PROCESSING
        import_log.current_stage = "Analyzing files"
        db.commit()

        # Process each CSV file
        csv_files = [f for f in os.listdir(f"uploads/imports/{uuid}") if f.endswith('.csv')]
        print(f"Found CSV files: {csv_files}")
        if not csv_files:
            print("No CSV files found")
            import_log.status = ImportStatus.FAILED
            import_log.error_message = "No CSV files found in upload"
            db.commit()
            return
        global total_rows
        for file in csv_files:
            total_rows += len(pd.read_csv(f"uploads/imports/{uuid}/{file}"))

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
                "patterns": ["invoices", "invoice"],
                "processor": process_invoice_data,
                "stage_name": "Processing Invoice Data"
            },
            {
                "patterns": ["payments", "payment"],
                "processor": process_payment_data,
                "stage_name": "Processing Payment Data"
            },
            {
                "patterns": ["procedure catalog", "procedure-catalog", "procedure_catalog", "procedurecatalog"],
                "processor": process_procedure_catalog_data,
                "stage_name": "Processing Procedure Catalog"
            }
        ]

        total_files = len(csv_files)
        files_processed = 0
        import_log.total_files = total_files

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
                                      process_invoice_data, process_payment_data, process_procedure_catalog_data, process_treatment_data, process_clinical_note_data, process_treatment_plan_data]:
                            await processor(import_log, df, db, user)
                        else:
                            await processor(import_log, df, db)
                            
                        files_processed += 1
                        import_log.files_processed = files_processed
                        db.commit()
                            
                    except Exception as e:
                        print(f"Error processing file {filename}: {str(e)}")
                        import_log.error_message = f"Error in {filename}: {str(e)}"
                        continue

        # Update import log status to completed
        import_log.status = ImportStatus.COMPLETED
        import_log.current_file = None
        import_log.current_stage = f"Import Completed - Processed {total_rows} total rows"
        import_log.progress = 100
        db.commit()
        print(f"Import completed successfully. Total rows processed: {total_rows}")
        
    except Exception as e:
        print(f"Error in background processing: {str(e)}")
        if 'import_log' in locals():
            if import_log:
                import_log.status = ImportStatus.FAILED
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
async def import_data(background_tasks: BackgroundTasks, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        # clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
        # if not clinic:
        #     return JSONResponse(status_code=404, content={"error": "Clinic not found"})
        
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
            # clinic_id=clinic.id,
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
        db.refresh(import_log)
        
        # Read and save file
        file_contents = await file.read()
        file_path = f"uploads/imports/{uuid}/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(file_contents)
            
        if file_ext == '.zip':
            import_log.zip_file = file_path
            db.commit()

        # Start background processing without using scheduler
        # This avoids timezone and scheduler issues
        process = Process(target=run_process_data_in_background, args=(file_path, user.id, import_log.id, uuid))
        process.daemon = True
        process.start()

        return JSONResponse(status_code=200, content={
            "message": "Data import started",
            "import_log_id": import_log.id
        })

    except Exception as e:
        if 'import_log' in locals():
            import_log.status = ImportStatus.FAILED
            import_log.error_message = f"Failed to start import: {str(e)}"
            db.commit()
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

# Helper function to run in a separate process
def run_process_data_in_background(file_path, user_id, import_log_id, uuid):
    from db.db import SessionLocal
    db = SessionLocal()
    try:
        # Use asyncio to properly await the async function
        import asyncio
        asyncio.run(process_data_in_background(file_path, user_id, import_log_id, db, uuid))
    finally:
        db.close()

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

        return JSONResponse(status_code=200, content=[
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
            ])
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.websocket("/ws/import-logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        # Get auth token from first message
        auth_message = await websocket.receive_json()
        token = auth_message.get("authorization", "")
        
        if not token or not token.startswith("Bearer "):
            await websocket.send_json({"error": "Invalid or missing authorization"})
            await websocket.close()
            return
            
        # Verify token
        try:
            decoded_token = decode_token(token.split(" ")[1])
            user_id = decoded_token["user_id"]
        except:
            await websocket.send_json({"error": "Invalid token"})
            await websocket.close()
            return
            
        # Start sending log updates
        while True:
            db = SessionLocal()
            try:
                logs = db.query(ImportLog)\
                    .filter(ImportLog.user_id == user_id)\
                    .order_by(ImportLog.created_at.desc())\
                    .all()
                    
                log_list = [{
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
                } for log in logs]
                
                await websocket.send_json(log_list)
                await asyncio.sleep(1)
                
            finally:
                db.close()
                
    except Exception as e:
        print(f"WebSocket error: {str(e)}")
        
    finally:
        try:
            await websocket.close()
        except:
            pass

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
    - Color code
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
                            "color_code": "#000000",
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
                "color_code": user.color_code,
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
    
    Returns a paginated list of all users with user_type='doctor' including:
    - Doctor ID
    - Name
    - Email
    - Phone
    - Bio
    - Profile picture URL
    - Color code
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
    - name: Search by doctor name
    - email: Search by doctor email
    - phone: Search by doctor phone number
    - doctor_id: Search by doctor ID
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Notes:
    - Returns ALL users with type 'doctor' regardless of who is making the request
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
                            "color_code": "#000000",
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
    per_page: int = Query(default=25, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)"),
    name: Optional[str] = Query(None, description="Search by doctor name"),
    email: Optional[str] = Query(None, description="Search by doctor email"),
    phone: Optional[str] = Query(None, description="Search by doctor phone"),
    doctor_id: Optional[str] = Query(None, description="Search by doctor ID"),
    db: Session = Depends(get_db)
):
    try:
        from sqlalchemy import or_, and_
        
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Build base query - get ALL doctors
        query = db.query(User).filter(User.user_type == "doctor")
        
        # Apply search filters if provided
        search_filters = []
        if name:
            search_filters.append(User.name.ilike(f"%{name}%"))
        if email:
            search_filters.append(User.email.ilike(f"%{email}%"))
        if phone:
            search_filters.append(User.phone.ilike(f"%{phone}%"))
        if doctor_id:
            search_filters.append(User.id == doctor_id)
            
        if search_filters:
            query = query.filter(or_(*search_filters))
        
        # Get total count
        total = query.count()
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
        
        # Add sorting
        if hasattr(User, sort_by):
            sort_column = getattr(User, sort_by)
            if sort_order.lower() == 'desc':
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        
        # Get paginated doctors - ALL doctors in the system
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
                "color_code": doctor.color_code,
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
    - Patient statistics (monthly breakdown, total count)
    - Appointment metrics (monthly breakdown, total count)
    - Prescription data (monthly breakdown, total count)
    - Financial overview (monthly breakdown, total earnings)
    - Recent transactions and patients
    
    Query parameters:
    - time_range: Optional time range filter (options: "this_month", "this_year", "3_months", "6_months", "1_year", "3_years", "all_time", default: "1_year")
    - clinic_id: Optional clinic ID to filter statistics by clinic
    """
)
async def get_dashboard(
    request: Request, 
    time_range: str = Query("1_year", description="Time range for statistics (this_month, this_year, 3_months, 6_months, 1_year, 3_years, all_time)"),
    clinic_id: Optional[str] = None, 
    db: Session = Depends(get_db)
):
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
        current_year = today.year
        current_month = today.month

        # Calculate last month
        if current_month == 1:
            last_month = 12
            last_month_year = current_year - 1
        else:
            last_month = current_month - 1
            last_month_year = current_year

        # Determine start date based on time_range
        if time_range == "this_month":
            start_date = datetime(current_year, current_month, 1)
            months_to_show = 1
        elif time_range == "this_year":
            start_date = datetime(current_year, 1, 1)
            months_to_show = current_month
        elif time_range == "3_months":
            if current_month <= 3:
                start_year = current_year - 1
                start_month = current_month + 9
            else:
                start_year = current_year
                start_month = current_month - 3
            start_date = datetime(start_year, start_month, 1)
            months_to_show = 3
        elif time_range == "6_months":
            if current_month <= 6:
                start_year = current_year - 1
                start_month = current_month + 6
            else:
                start_year = current_year
                start_month = current_month - 6
            start_date = datetime(start_year, start_month, 1)
            months_to_show = 6
        elif time_range == "1_year":
            start_date = datetime(current_year - 1, current_month, 1)
            months_to_show = 12
        elif time_range == "3_years":
            start_date = datetime(current_year - 3, current_month, 1)
            months_to_show = 36
        else:  # all_time
            start_date = datetime(current_year - 1, current_month, 1)
            months_to_show = 12

        # Generate list of months to display
        months_list = []
        month_names = ["January", "February", "March", "April", "May", "June", 
                      "July", "August", "September", "October", "November", "December"]
        
        temp_date = start_date
        for _ in range(months_to_show):
            months_list.append({
                "name": month_names[temp_date.month - 1],
                "year": temp_date.year,
                "month": temp_date.month,
                "start_date": datetime(temp_date.year, temp_date.month, 1),
                "end_date": datetime(temp_date.year + 1 if temp_date.month == 12 else temp_date.year, 
                                    1 if temp_date.month == 12 else temp_date.month + 1, 1)
            })
            if temp_date.month == 12:
                temp_date = datetime(temp_date.year + 1, 1, 1)
            else:
                temp_date = datetime(temp_date.year, temp_date.month + 1, 1)
        
        months_list.reverse()

        # Current and last month date ranges
        current_month_start = datetime(current_year, current_month, 1)
        current_month_end = datetime(current_year + 1, 1, 1) if current_month == 12 else datetime(current_year, current_month + 1, 1)
        
        last_month_start = datetime(last_month_year, last_month, 1)
        last_month_end = datetime(current_year, current_month, 1)

        # Patient Statistics
        patient_query = db.query(Patient).filter(*base_filters)
        if time_range != "all_time":
            patient_query = patient_query.filter(Patient.created_at >= start_date)
            
        total_patients = patient_query.count()
        recent_patients = patient_query.order_by(Patient.created_at.desc()).limit(10).all()
        
        # Get monthly patient counts and growth
        current_month_patients = db.query(Patient).filter(
            *base_filters,
            Patient.created_at >= current_month_start,
            Patient.created_at < current_month_end
        ).count()

        last_month_patients = db.query(Patient).filter(
            *base_filters,
            Patient.created_at >= last_month_start,
            Patient.created_at < last_month_end
        ).count()

        patient_growth = 0
        if last_month_patients > 0:
            patient_growth = ((current_month_patients - last_month_patients) / last_month_patients) * 100

        monthly_patients = {}
        for month_data in months_list:
            count = db.query(Patient).filter(
                *base_filters,
                Patient.created_at >= month_data["start_date"],
                Patient.created_at < month_data["end_date"]
            ).count()
            
            month_key = f"{month_data['name']} {month_data['year']}"
            monthly_patients[month_key] = count

        # Appointment Statistics
        appointment_base_filters = [
            Appointment.doctor_id == user.id,
            *([Appointment.clinic_id == clinic_id] if clinic_id else [])
        ]
        
        appointment_query = db.query(Appointment).filter(*appointment_base_filters)
        if time_range != "all_time":
            appointment_query = appointment_query.filter(Appointment.created_at >= start_date)
            
        total_appointments = appointment_query.count()

        # Get appointment counts and growth
        current_month_appointments = db.query(Appointment).filter(
            *appointment_base_filters,
            Appointment.created_at >= current_month_start,
            Appointment.created_at < current_month_end
        ).count()

        last_month_appointments = db.query(Appointment).filter(
            *appointment_base_filters,
            Appointment.created_at >= last_month_start,
            Appointment.created_at < last_month_end
        ).count()

        appointment_growth = 0
        if last_month_appointments > 0:
            appointment_growth = ((current_month_appointments - last_month_appointments) / last_month_appointments) * 100
        
        monthly_appointments = {}
        for month_data in months_list:
            count = db.query(Appointment).filter(
                *appointment_base_filters,
                Appointment.created_at >= month_data["start_date"],
                Appointment.created_at < month_data["end_date"]
            ).count()
            
            month_key = f"{month_data['name']} {month_data['year']}"
            monthly_appointments[month_key] = count
        
        today_appointments = db.query(Appointment).filter(
            *appointment_base_filters,
            Appointment.appointment_date >= today,
            Appointment.appointment_date < today + timedelta(days=1)
        ).order_by(Appointment.appointment_date.asc()).all()
        
        upcoming_appointments = db.query(Appointment).filter(
            *appointment_base_filters,
            Appointment.appointment_date > today,
            Appointment.status == AppointmentStatus.SCHEDULED
        ).count()

        # Prescription Statistics
        prescription_base_filters = [
            ClinicalNote.doctor_id == user.id,
            *([ClinicalNote.clinic_id == clinic_id] if clinic_id else [])
        ]
        
        prescription_query = db.query(ClinicalNote).filter(*prescription_base_filters)
        if time_range != "all_time":
            prescription_query = prescription_query.filter(ClinicalNote.created_at >= start_date)
            
        total_prescriptions = prescription_query.count()

        # Get prescription counts and growth
        current_month_prescriptions = db.query(ClinicalNote).filter(
            *prescription_base_filters,
            ClinicalNote.created_at >= current_month_start,
            ClinicalNote.created_at < current_month_end
        ).count()

        last_month_prescriptions = db.query(ClinicalNote).filter(
            *prescription_base_filters,
            ClinicalNote.created_at >= last_month_start,
            ClinicalNote.created_at < last_month_end
        ).count()

        prescription_growth = 0
        if last_month_prescriptions > 0:
            prescription_growth = ((current_month_prescriptions - last_month_prescriptions) / last_month_prescriptions) * 100
        
        monthly_prescriptions = {}
        for month_data in months_list:
            count = db.query(ClinicalNote).filter(
                *prescription_base_filters,
                ClinicalNote.created_at >= month_data["start_date"],
                ClinicalNote.created_at < month_data["end_date"]
            ).count()
            
            month_key = f"{month_data['name']} {month_data['year']}"
            monthly_prescriptions[month_key] = count

        # Financial Statistics
        payment_base_filters = [
            Payment.doctor_id == user.id,
            Payment.cancelled == False,
            *([Payment.clinic_id == clinic_id] if clinic_id else [])
        ]
        
        payment_query = db.query(Payment).filter(*payment_base_filters)
        if time_range != "all_time":
            payment_query = payment_query.filter(Payment.date >= start_date)
            
        total_payments = payment_query.all()
        total_earnings = sum(payment.amount_paid or 0 for payment in total_payments)

        # Get earnings and growth
        current_month_payments = db.query(Payment).filter(
            *payment_base_filters,
            Payment.date >= current_month_start,
            Payment.date < current_month_end
        ).all()
        current_month_earnings = sum(payment.amount_paid or 0 for payment in current_month_payments)

        last_month_payments = db.query(Payment).filter(
            *payment_base_filters,
            Payment.date >= last_month_start,
            Payment.date < last_month_end
        ).all()
        last_month_earnings = sum(payment.amount_paid or 0 for payment in last_month_payments)

        earnings_growth = 0
        if last_month_earnings > 0:
            earnings_growth = ((current_month_earnings - last_month_earnings) / last_month_earnings) * 100
        
        monthly_earnings = {}
        for month_data in months_list:
            month_payments = db.query(Payment).filter(
                *payment_base_filters,
                Payment.date >= month_data["start_date"],
                Payment.date < month_data["end_date"]
            ).all()
            
            earnings = sum(payment.amount_paid or 0 for payment in month_payments)
            month_key = f"{month_data['name']} {month_data['year']}"
            monthly_earnings[month_key] = round(earnings, 2)
        
        recent_transactions = payment_query.order_by(Payment.created_at.desc()).limit(10).all()

        return JSONResponse(status_code=200, content={
            "time_range": time_range,
            "patient_statistics": {
                "total_patients": total_patients,
                "monthly_patients": monthly_patients,
                "current_month_patients": current_month_patients,
                "last_month_patients": last_month_patients,
                "growth_percentage": round(patient_growth, 2),
                "recent_patients": [{
                    "id": patient.id,
                    "name": patient.name,
                    "mobile_number": patient.mobile_number,
                    "email": patient.email,
                    "gender": patient.gender.value if hasattr(patient.gender, 'value') else patient.gender,
                    "created_at": patient.created_at.strftime("%Y-%m-%d %H:%M") if patient.created_at else None
                } for patient in recent_patients]
            },
            "appointment_statistics": {
                "total_appointments": total_appointments,
                "monthly_appointments": monthly_appointments,
                "current_month_appointments": current_month_appointments,
                "last_month_appointments": last_month_appointments,
                "growth_percentage": round(appointment_growth, 2),
                "upcoming_appointments": upcoming_appointments,
                "today_appointments": [{
                    "id": appt.id,
                    "patient_name": appt.patient_name,
                    "time": appt.appointment_date.strftime("%H:%M") if appt.appointment_date else None,
                    "status": appt.status.value if hasattr(appt.status, 'value') else appt.status,
                    "notes": appt.notes
                } for appt in today_appointments]
            },
            "prescription_statistics": {
                "total_prescriptions": total_prescriptions,
                "monthly_prescriptions": monthly_prescriptions,
                "current_month_prescriptions": current_month_prescriptions,
                "last_month_prescriptions": last_month_prescriptions,
                "growth_percentage": round(prescription_growth, 2)
            },
            "financial_statistics": {
                "total_earnings": round(total_earnings, 2),
                "monthly_earnings": monthly_earnings,
                "current_month_earnings": round(current_month_earnings, 2),
                "last_month_earnings": round(last_month_earnings, 2),
                "growth_percentage": round(earnings_growth, 2),
                "recent_transactions": [{
                    "date": payment.date.strftime("%Y-%m-%d %H:%M") if payment.date else None,
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