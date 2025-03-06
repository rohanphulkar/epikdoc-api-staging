from fastapi import APIRouter, Depends, Request, File, UploadFile, BackgroundTasks
from db.db import get_db
from sqlalchemy.orm import Session
from .models import User, ProcedureCatalog, ImportLog, ImportStatus
from .schemas import *
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from utils.auth import (
    validate_email, validate_phone, validate_password, signJWT, decodeJWT,
    verify_password, get_password_hash, generate_reset_token, verify_token, generate_otp
)
from utils.email import send_forgot_password_email
from utils.send_otp import send_otp_via_phone
from gauthuserinfo import get_user_info
import zipfile
import os
import pandas as pd
from appointment.models import *
from patient.models import *
from payment.models import *
from prediction.models import *
from typing import List

user_router = APIRouter()

@user_router.post("/register", 
    response_model=dict,
    status_code=201,
    summary="Register a new user",
    description="""
    Create a new user account with the following required fields:
    
    - email: Valid email address (e.g. user@example.com)
    - password: Strong password that meets security requirements:
        - Minimum 8 characters
        - At least 1 uppercase letter
        - At least 1 lowercase letter 
        - At least 1 number
    - name: User's full name
    - phone: Valid phone number with country code (e.g. +1234567890)
    - user_type: Type of user account ("doctor" or "admin")
    
    Returns success message on successful registration.
    """,
    responses={
        201: {
            "description": "User created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "User created successfully"
                    }
                }
            }
        },
        400: {
            "description": "Bad request - Invalid input or user already exists",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Invalid email format | User already exists with this email/phone"
                    }
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
        
        return JSONResponse(status_code=201, content={"message": "User created successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/login", 
    response_model=dict, 
    status_code=200, 
    summary="Login user",
    description="""
    Authenticate user and get access token.
    
    Required fields:
    - email: Registered email address
    - password: Account password
    
    Returns JWT access token on successful login.
    """,
    responses={
        200: {
            "description": "Login successful",
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
        401: {
            "description": "Authentication failed",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid credentials"}
                }
            }
        }
    }
)
async def login(user: UserSchema, db: Session = Depends(get_db)):
    try:
        if not user.email or not user.password:
            return JSONResponse(status_code=400, content={"error": "Email and password are required"})
         
        db_user = db.query(User).filter(User.email == user.email).first()

        if not db_user:
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
        
        if not db_user.is_active:
            return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})
    
        if not db_user or not verify_password(user.password, str(db_user.password)):
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
        
        setattr(db_user, 'last_login', datetime.now())
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
    Get authenticated user's complete profile information.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Returns user profile data including:
    - Name
    - Email
    - Phone number
    - Bio
    - Profile picture URL
    """,
    responses={
        200: {
            "description": "User profile retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "name": "John Doe",
                        "email": "john@example.com",
                        "phone": "+1234567890",
                        "bio": "Doctor specializing in pediatrics",
                        "profile_pic": "http://example.com/uploads/profile.jpg"
                    }
                }
            }
        },
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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

        if user.profile_pic:
            profile_pic = f"{request.base_url}{user.profile_pic}"
            user_data["profile_pic"] = profile_pic
        else:
            user_data["profile_pic"] = None
        
        return JSONResponse(status_code=200, content=user_data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.get("/created-doctors",
    response_model=dict,
    status_code=200,
    summary="Get created doctors",
    description="""
    Get list of all doctors created by the authenticated admin user.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Returns array of doctor profiles including:
    - ID
    - Name  
    - Email
    - Phone
    - User type
    """,
    responses={
        200: {
            "description": "Created doctors retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "doctors": [
                            {
                                "id": "uuid",
                                "name": "Dr. Smith",
                                "email": "smith@hospital.com",
                                "phone": "+1234567890",
                                "user_type": "doctor"
                            }
                        ]
                    }
                }
            }
        },
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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

        return JSONResponse(status_code=200, content={"doctors": doctors_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/forgot-password",
    response_model=dict,
    status_code=200,
    summary="Forgot password",
    description="""
    Initiate password reset process by sending reset link via email.
    
    Required fields:
    - email: Registered email address
    
    A password reset link will be sent to the provided email if it exists in the system.
    The reset token expires after 3 hours.
    """,
    responses={
        200: {
            "description": "Password reset email sent",
            "content": {
                "application/json": {
                    "example": {"message": "Password reset email sent"}
                }
            }
        },
        400: {"description": "Invalid email"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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
        reset_link = f"{request.headers.get('origin') or request.base_url}/reset-password?token={reset_token}"
        
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
    summary="Reset password",
    description="""
    Reset user password using the token received via email.
    
    Required query parameter:
    - token: Reset token from email link
    
    Required fields in request body:
    - password: New password meeting security requirements
    - confirm_password: Must match new password
    
    Password requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    """,
    responses={
        200: {
            "description": "Password reset successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Password reset successfully"}
                }
            }
        },
        400: {"description": "Invalid input or expired token"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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
    - new_password: New password meeting security requirements
    - confirm_new_password: Must match new password
    
    Password requirements:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
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
        400: {"description": "Invalid input"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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
    summary="Update profile",
    description="""
    Update authenticated user's profile information.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Optional fields:
    - name: New display name
    - phone: New phone number with country code
    - bio: Brief user biography/description
    - image: Profile image file (JPG/PNG)
    
    The profile picture will be stored in the uploads/profile_pictures directory.
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
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_profile(user: UserProfileUpdateSchema, request: Request, image: UploadFile = File(None), db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        
        db_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if user.name:
            setattr(db_user, 'name', user.name)
        if user.phone:
            setattr(db_user, 'phone', user.phone)
        if user.bio:
            setattr(db_user, 'bio', user.bio)
            
        if image:
            # Read file contents
            file_contents = await image.read()
            
            # Save file to disk/storage
            file_name = f"profile_{db_user.id}_{image.filename}"
            file_path = f"uploads/profile_pictures/{file_name}"
            
            with open(file_path, "wb") as f:
                f.write(file_contents)
                
            # Update user profile URL in database
            setattr(db_user, 'profile_pic', str(file_path))
            
        db.commit()
        db.refresh(db_user)
        return JSONResponse(status_code=200, content={"message": "Profile updated successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.delete("/delete-profile",
    response_model=dict,
    status_code=200,
    summary="Delete profile",
    description="""
    Permanently delete authenticated user's profile and all associated data.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    This action cannot be undone. All user data will be removed from the database.
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
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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
    summary="Google login",
    description="""
    Authenticate user using Google OAuth token.
    
    Required fields:
    - token: Valid Google OAuth token
    
    If user doesn't exist, a new account will be created using Google profile data.
    Returns JWT access token on successful authentication.
    """,
    responses={
        200: {
            "description": "Google login successful",
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
        401: {"description": "Account deactivated"},
        500: {"description": "Internal server error"}
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
    summary="Check token validity",
    description="""
    Verify if the provided JWT token is valid and not expired.
    
    Required headers:
    - Authorization: Bearer {access_token}
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
            "description": "Token is invalid",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid token"}
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
    summary="Deactivate account",
    description="""
    Temporarily deactivate authenticated user's account.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Account can be reactivated by admin later.
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
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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
    for _, row in df.iterrows():
        try:
            gender_str = str(row.get("Gender", "male")).lower()
            if "f" in gender_str or "female" in gender_str:
                gender = Gender.FEMALE
            else:
                gender = Gender.MALE

            patient_number = str(row.get("Patient Number", ""))
            print(f"Looking up patient number: {patient_number}")
            patient = db.query(Patient).filter(Patient.patient_number == patient_number).first()
            if not patient:
                print(f"Creating new patient with number: {patient_number}")
                patient = Patient(
                    doctor_id=user.id,
                    patient_number=str(row.get("Patient Number", ""))[:255],
                    name=str(row.get("Patient Name", ""))[:255],
                    mobile_number=str(row.get("Mobile Number", ""))[:255],
                    contact_number=str(row.get("Contact Number", ""))[:255],
                    email=str(row.get("Email Address", ""))[:255],
                    secondary_mobile=str(row.get("Secondary Mobile", ""))[:255],
                    gender=gender,
                    address=str(row.get("Address", ""))[:255],
                    locality=str(row.get("Locality", ""))[:255],
                    city=str(row.get("City", ""))[:255],
                    pincode=str(row.get("Pincode", ""))[:255],
                    national_id=str(row.get("National Id", ""))[:255],
                    date_of_birth=pd.to_datetime(str(row.get("Date of Birth"))) if row.get("Date of Birth") else None,
                    age=str(row.get("Age", ""))[:5],
                    anniversary_date=pd.to_datetime(str(row.get("Anniversary Date"))) if row.get("Anniversary Date") else None,
                    blood_group=str(row.get("Blood Group", ""))[:50],
                    remarks=str(row.get("Remarks", "")),
                    medical_history=str(row.get("Medical History", "")),
                    referred_by=str(row.get("Referred By", ""))[:255],
                    groups=str(row.get("Groups", ""))[:255],
                    patient_notes=str(row.get("Patient Notes", ""))
                )
                db.add(patient)
        except Exception as e:
            print(f"Error processing patient row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing patient row: {str(e)}"})

async def process_appointment_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing appointment data")
    for _, row in df.iterrows():
        try:
            status_str = str(row.get("Status", "SCHEDULED")).upper()
            if status_str == "SCHEDULED":
                status = AppointmentStatus.SCHEDULED
            else:
                status = AppointmentStatus.CANCELLED

            patient_number = str(row.get("Patient Number", ""))
            print(f"Looking up patient number: {patient_number}")
            patient = db.query(Patient).filter(Patient.patient_number == patient_number).first()
            if not patient:
                print(f"Patient not found for number: {patient_number}")
                continue
            
            appointment = Appointment(
                patient_id=patient.id,
                patient_number=str(row.get("Patient Number", ""))[:255],
                patient_name=str(row.get("Patient Name", ""))[:255],
                doctor_id=user.id,
                doctor_name=str(row.get("DoctorName", ""))[:255],
                notes=str(row.get("Notes", "")),
                appointment_date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                checked_in_at=pd.to_datetime(str(row.get("Checked In At"))) if row.get("Checked In At") else None,
                checked_out_at=pd.to_datetime(str(row.get("Checked Out At"))) if row.get("Checked Out At") else None,
                status=status
            )
            db.add(appointment)
        except Exception as e:
            print(f"Error processing appointment row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing appointment row: {str(e)}"})

async def process_treatment_data(import_log: ImportLog, df: pd.DataFrame, db: Session):
    print("Processing treatment data")
    for _, row in df.iterrows():
        try:
         
            patient_number = str(row.get("Patient Number", ""))
            print(f"Looking up patient number: {patient_number}")
            patient = db.query(Patient).filter(Patient.patient_number == patient_number).first()
            if not patient:
                print(f"Patient not found for number: {patient_number}")
                continue

            treatment = Treatment(
                patient_id=patient.id,
                treatment_date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                treatment_name=str(row.get("Treatment Name", "")).strip("'")[:255],
                tooth_number=str(row.get("Tooth Number", "")).strip("'")[:50],
                treatment_notes=str(row.get("Treatment Notes", "")).strip("'"),
                quantity=int(float(str(row.get("Quantity", 0)).strip("'"))),
                treatment_cost=float(str(row.get("Treatment Cost", 0.0)).strip("'")),
                amount=float(str(row.get("Amount", 0.0)).strip("'")),
                discount=float(str(row.get("Discount", 0)).strip("'")),
                discount_type=str(row.get("DiscountType", "")).strip("'")[:50],
                doctor=str(row.get("Doctor", "")).strip("'")[:255]
            )
            db.add(treatment)
        except Exception as e:
            print(f"Error processing treatment row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing treatment row: {str(e)}"})

async def process_clinical_note_data(import_log: ImportLog, df: pd.DataFrame, db: Session):
    print("Processing clinical note data")
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            print(f"Looking up patient number: {patient_number}")
            patient = db.query(Patient).filter(Patient.patient_number == patient_number).first()
            if not patient:
                print(f"Patient not found for number: {patient_number}")
                continue
            
            note = ClinicalNote(
                patient_id=patient.id,
                date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                doctor=str(row.get("Doctor", ""))[:255],
                note_type=str(row.get("Type", ""))[:255],
                description=str(row.get("Description", "")),
                is_revised=bool(row.get("Revised", False))
            )
            db.add(note)
        except Exception as e:
            print(f"Error processing clinical note row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing clinical note row: {str(e)}"})

async def process_treatment_plan_data(import_log: ImportLog, df: pd.DataFrame, db: Session):
    print("Processing treatment plan data")
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            print(f"Looking up patient number: {patient_number}")
            patient = db.query(Patient).filter(Patient.patient_number == patient_number).first()
            if not patient:
                print(f"Patient not found for number: {patient_number}")
                continue
            
            plan = TreatmentPlan(
                patient_id=patient.id,
                date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                doctor=str(row.get("Doctor", ""))[:255],
                treatment_name=str(row.get("Treatment Name", ""))[:255],
                unit_cost=float(row.get("UnitCost", 0.0)),
                quantity=int(row.get("Quantity", 1)),
                discount=float(row.get("Discount", 0)) if row.get("Discount") else None,
                discount_type=str(row.get("DiscountType", ""))[:50],
                amount=float(row.get("Amount", 0.0)),
                treatment_description=str(row.get("Treatment Description", "")),
                tooth_diagram=str(row.get("Tooth Diagram", ""))
            )
            db.add(plan)
        except Exception as e:
            print(f"Error processing treatment plan row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing treatment plan row: {str(e)}"})

async def process_expense_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing expense data")
    for _, row in df.iterrows():
        try:
            amount_str = str(row.get("Amount", "0.0")).strip("'")
            expense = Expense(
                date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                doctor_id=user.id,
                expense_type=str(row.get("Expense Type", ""))[:255],
                description=str(row.get("Description", "")),
                amount=float(amount_str),
                vendor_name=str(row.get("Vendor Name", ""))[:255]
            )
            db.add(expense)
        except Exception as e:
            print(f"Error processing expense row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing expense row: {str(e)}"})

async def process_payment_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing payment data")
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            print(f"Looking up patient number: {patient_number}")
            patient = db.query(Patient).filter(Patient.patient_number == patient_number).first()
            if not patient:
                print(f"Patient not found for number: {patient_number}")
                continue
            
            # Handle potential string values with quotes for numeric fields
            try:
                amount_paid = float(str(row.get("Amount Paid", 0.0)).strip("'"))
            except (ValueError, TypeError):
                print("Error parsing amount paid, defaulting to 0.0")
                amount_paid = 0.0

            try:
                refunded_amount = float(str(row.get("Refunded amount")).strip("'")) if row.get("Refunded amount") else None
            except (ValueError, TypeError):
                print("Error parsing refunded amount, defaulting to None")
                refunded_amount = None

            try:
                vendor_fees_percent = float(str(row.get("Vendor Fees Percent")).strip("'")) if row.get("Vendor Fees Percent") else None
            except (ValueError, TypeError):
                print("Error parsing vendor fees percent, defaulting to None")
                vendor_fees_percent = None

            payment = Payment(
                date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                doctor_id=user.id,
                patient_id=patient.id,
                patient_number=str(row.get("Patient Number", ""))[:255],
                patient_name=str(row.get("Patient Name", ""))[:255],
                receipt_number=str(row.get("Receipt Number", ""))[:255],
                treatment_name=str(row.get("Treatment name", ""))[:255],
                amount_paid=amount_paid,
                invoice_number=str(row.get("Invoice Number", ""))[:255],
                notes=str(row.get("Notes", "")),
                refund=bool(row.get("Refund", False)),
                refund_receipt_number=str(row.get("Refund Receipt Number", ""))[:255],
                refunded_amount=refunded_amount,
                payment_mode=str(row.get("Payment Mode", ""))[:255],
                card_number=str(row.get("Card Number", ""))[:255],
                card_type=str(row.get("Card Type", ""))[:255],
                cheque_number=str(row.get("Cheque Number", ""))[:255],
                cheque_bank=str(row.get("Cheque Bank", ""))[:255],
                netbanking_bank_name=str(row.get("Netbanking Bank Name", ""))[:255],
                vendor_name=str(row.get("Vendor Name", ""))[:255],
                vendor_fees_percent=vendor_fees_percent,
                cancelled=bool(row.get("Cancelled", False))
            )
            db.add(payment)
        except Exception as e:
            print(f"Error processing payment row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing payment row: {str(e)}"})

async def process_invoice_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing invoice data")
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            print(f"Looking up patient number: {patient_number}")
            patient = db.query(Patient).filter(Patient.patient_number == patient_number).first()
            if not patient:
                print(f"Patient not found for number: {patient_number}")
                continue
            
            discount_type_str = row.get("DiscountType")
            if discount_type_str:
                try:
                    discount_type = DiscountType[discount_type_str.upper()]
                except KeyError:
                    print(f"Invalid discount type: {discount_type_str}")
                    discount_type = None
            else:
                discount_type = None

            # Handle potential string values with quotes for numeric fields
            try:
                unit_cost = float(str(row.get("Unit Cost", 0.0)).strip("'"))
            except (ValueError, TypeError):
                print("Error parsing unit cost, defaulting to 0.0")
                unit_cost = 0.0

            try:
                discount = float(str(row.get("Discount")).strip("'")) if row.get("Discount") else None
            except (ValueError, TypeError):
                print("Error parsing discount, defaulting to None")
                discount = None

            try:
                invoice_level_tax_discount = float(str(row.get("Invoice Level Tax Discount")).strip("'")) if row.get("Invoice Level Tax Discount") else None
            except (ValueError, TypeError):
                print("Error parsing invoice level tax discount, defaulting to None")
                invoice_level_tax_discount = None

            try:
                tax_percent = float(str(row.get("Tax Percent")).strip("'")) if row.get("Tax Percent") else None
            except (ValueError, TypeError):
                print("Error parsing tax percent, defaulting to None")
                tax_percent = None

            try:
                quantity = int(str(row.get("Quantity", 1)).strip("'"))
            except (ValueError, TypeError):
                print("Error parsing quantity, defaulting to 1")
                quantity = 1

            invoice = Invoice(
                date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                doctor_id=user.id,
                patient_id=patient.id,
                patient_number=str(row.get("Patient Number", ""))[:255],
                patient_name=str(row.get("Patient Name", ""))[:255],
                doctor_name=str(row.get("Doctor Name", ""))[:255],
                invoice_number=str(row.get("Invoice Number", ""))[:255],
                treatment_name=str(row.get("Treatment Name", ""))[:255],
                unit_cost=unit_cost,
                quantity=quantity,
                discount=discount,
                discount_type=discount_type,
                type=str(row.get("Type", ""))[:255],
                invoice_level_tax_discount=invoice_level_tax_discount,
                tax_name=str(row.get("Tax name", ""))[:255],
                tax_percent=tax_percent,
                cancelled=bool(row.get("Cancelled", False)),
                notes=str(row.get("Notes", "")),
                description=str(row.get("Description", ""))
            )
            db.add(invoice)
        except Exception as e:
            print(f"Error processing invoice row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing invoice row: {str(e)}"})

async def process_procedure_catalog_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing procedure catalog data")
    for _, row in df.iterrows():
        try:
            try:
                treatment_cost = float(row.get("Treatment Cost", 0.0))
            except (ValueError, TypeError):
                print("Error parsing treatment cost, defaulting to 0.0")
                treatment_cost = 0.0
            
            try:
                procedure = ProcedureCatalog(
                    user_id=user.id,
                    treatment_name=str(row.get("Treatment Name", ""))[:255],
                    treatment_cost=treatment_cost,
                    treatment_notes=str(row.get("Treatment Notes", "")),
                    locale=str(row.get("Locale", ""))[:50]
                )
                db.add(procedure)
            except Exception as e:
                print(f"Error creating procedure catalog: {str(e)}")
                raise
        except Exception as e:
            print(f"Error processing procedure catalog row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing procedure catalog row: {str(e)}"})

async def process_data_in_background(file_path: str, user_id: str, import_log_id: str, db: Session):
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
                with zipfile.ZipFile(file_path, "r") as zip_ref:
                    zip_ref.extractall("uploads")
                print("Zip file extracted successfully")
            except Exception as e:
                print(f"Error extracting zip file: {str(e)}")
                import_log.status = ImportStatus.FAILED
                db.commit()
                return

        # Update status to processing
        import_log.status = ImportStatus.PROCESSING
        db.commit()
        print("Updated import status to PROCESSING")

        # Process each CSV file
        csv_files = [f for f in os.listdir("uploads") if f.endswith('.csv')]
        print(f"Found CSV files: {csv_files}")
        if not csv_files:
            print("No CSV files found")
            import_log.status = ImportStatus.FAILED
            db.commit()
            return

        # Define processing order
        file_types = [
            ["patients", "patient"],
            ["appointments", "appointment"], 
            ["treatments", "treatment"],
            ["clinicalnotes", "clinical-notes", "clinical_notes"],
            ["treatmentplans", "treatment-plans", "treatment_plans"],
            ["expenses", "expense"],
            ["payments", "payment"],
            ["invoices", "invoice"],
            ["procedurecatalog", "procedure-catalog", "procedure_catalog"]
        ]

        # Process files in order
        for file_type in file_types:
            print(f"\nProcessing file type: {file_type}")
            for filename in csv_files:
                normalized_filename = filename.lower().replace(" ", "").replace("-", "")
                if not any(name in normalized_filename for name in file_type):
                    continue

                print(f"\nProcessing file: {filename}")
                try:
                    print(f"Reading CSV file: {filename}")
                    df = pd.read_csv(f"uploads/{filename}", keep_default_na=False)
                    df = df.fillna("")
                    print(f"Successfully read CSV with {len(df)} rows")
                except Exception as e:
                    print(f"Error reading CSV file {filename}: {str(e)}")
                    continue
                
                try:
                    with db.no_autoflush:
                        if any(name in normalized_filename for name in ["patients.csv", "patient.csv"]):
                            print("Processing patients data...")
                            await process_patient_data(import_log, df, db, user)

                        elif any(name in normalized_filename for name in ["appointments.csv", "appointment.csv"]):
                            print("Processing appointments data...")
                            await process_appointment_data(import_log, df, db, user)

                        elif any(name in normalized_filename for name in ["treatments.csv", "treatment.csv"]):
                            print("Processing treatments data...")
                            await process_treatment_data(import_log, df, db)

                        elif any(name in normalized_filename for name in ["clinicalnotes.csv", "clinical-notes.csv", "clinical_notes.csv"]):
                            print("Processing clinical notes data...")
                            await process_clinical_note_data(import_log, df, db)

                        elif any(name in normalized_filename for name in ["treatmentplans.csv", "treatment-plans.csv", "treatment_plans.csv"]):
                            print("Processing treatment plans data...")
                            await process_treatment_plan_data(import_log, df, db)

                        elif any(name in normalized_filename for name in ["expenses.csv", "expense.csv"]):
                            print("Processing expenses data...")
                            await process_expense_data(import_log, df, db, user)

                        elif any(name in normalized_filename for name in ["payments.csv", "payment.csv"]):
                            print("Processing payments data...")
                            await process_payment_data(import_log, df, db, user)

                        elif any(name in normalized_filename for name in ["invoices.csv", "invoice.csv"]):
                            print("Processing invoices data...")
                            await process_invoice_data(import_log, df, db, user)

                        elif any(name in normalized_filename for name in ["procedurecatalog.csv", "procedure-catalog.csv", "procedure_catalog.csv"]):
                            print("Processing procedure catalog data...")
                            await process_procedure_catalog_data(import_log, df, db, user)
                        print("Committing changes to database...")
                        db.commit()
                        print("Successfully committed changes")

                except Exception as e:
                    print(f"Error processing file {filename}: {str(e)}")
                    db.rollback()
                    continue

        # Update import log status to completed
        import_log.status = ImportStatus.COMPLETED
        db.commit()
        print("Import completed successfully")
        
    except Exception as e:
        print(f"Error in background processing: {str(e)}")
        if 'import_log' in locals():
            if import_log:
                import_log.status = ImportStatus.FAILED
                db.commit()
                print("Updated import status to FAILED")
    finally:
        db.close()
        print("Database connection closed")

@user_router.post("/import-data",
    response_model=dict,
    status_code=200,
    summary="Import data from CSV or ZIP files",
    description="""
    Import data from CSV files or a ZIP archive containing CSV files.
    
    Supported file formats:
    - Single CSV file
    - ZIP archive containing multiple CSV files
    
    The CSV files should contain data for:
    - Patients
    - Appointments
    - Other related records
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Notes:
    - Files will be validated before processing
    - Data will be imported in a specific order to maintain referential integrity
    - Existing records may be updated based on unique identifiers
    """,
    responses={
        200: {
            "description": "Data import started",
            "content": {
                "application/json": {
                    "example": {"message": "Data import started", "import_log_id": 123}
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid file format. Only CSV and ZIP files are allowed."}
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing token"},
        404: {"description": "User not found"},
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
        
        # Create uploads directory if it doesn't exist
        os.makedirs("uploads", exist_ok=True)
        
        # Create import log entry
        import_log = ImportLog(
            user_id=user.id,
            file_name=file.filename,
            status=ImportStatus.PENDING
        )
        db.add(import_log)
        db.commit()
        
        # Read and save file
        file_contents = await file.read()
        file_path = f"uploads/imports/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(file_contents)
            
        if file_ext == '.zip':
            import_log.zip_file = file_path
            db.commit()

        # Start background processing
        background_tasks.add_task(process_data_in_background, file_path, user.id, import_log.id, db)

        return JSONResponse(status_code=200, content={
            "message": "Data import started",
            "import_log_id": import_log.id
        })

    except Exception as e:
        if 'import_log' in locals():
            import_log.status = ImportStatus.FAILED
            db.commit()
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.get("/get-import-logs",
    response_model=dict,
    status_code=200,
    summary="Get all import logs",
    description="Get all import logs for the authenticated user",
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
                                "created_at": "2024-01-01T00:00:00"
                            }
                        ]
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
async def get_import_logs(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        import_logs = db.query(ImportLog).filter(ImportLog.user_id == user.id).all()
        return JSONResponse(status_code=200, content={
            "import_logs": [
                {
                    "id": log.id,
                    "file_name": log.file_name,
                    "status": log.status.value,
                    "created_at": log.created_at.isoformat()
                } for log in import_logs
            ]
        })
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.post("/add-procedure-catalog",
    response_model=ProcedureCatalogResponse,
    status_code=201,
    summary="Add a new procedure catalog",
    description="Add a new procedure catalog entry for the authenticated user",
    responses={
        201: {
            "description": "Procedure catalog created successfully",
            "model": ProcedureCatalogResponse
        },
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
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
        
        return JSONResponse(status_code=201, content=ProcedureCatalogResponse.model_validate(procedure_catalog).model_dump())
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.get("/get-procedure-catalogs",
    response_model=List[ProcedureCatalogResponse],
    status_code=200,
    summary="Get all procedure catalogs",
    description="Get all procedure catalogs for the authenticated user",
    responses={
        200: {
            "description": "List of procedure catalogs",
            "model": List[ProcedureCatalogResponse]
        },
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_procedure_catalogs(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        procedure_catalogs = db.query(ProcedureCatalog).filter(ProcedureCatalog.user_id == user.id).all()
        return [ProcedureCatalogResponse.model_validate(pc) for pc in procedure_catalogs]
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.patch("/update-procedure-catalog/{procedure_id}",
    response_model=ProcedureCatalogResponse,
    status_code=200,
    summary="Update a procedure catalog",
    description="Update an existing procedure catalog entry",
    responses={
        200: {
            "description": "Procedure catalog updated successfully",
            "model": ProcedureCatalogResponse
        },
        401: {"description": "Unauthorized"},
        404: {"description": "User or procedure catalog not found"},
        500: {"description": "Internal server error"}
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
            procedure_catalog.treatment_name = procedure.treatment_name
        if procedure.treatment_cost is not None:
            procedure_catalog.treatment_cost = procedure.treatment_cost
        if procedure.treatment_notes is not None:
            procedure_catalog.treatment_notes = procedure.treatment_notes
        if procedure.locale is not None:
            procedure_catalog.locale = procedure.locale
        
        db.commit()
        db.refresh(procedure_catalog)
        
        return ProcedureCatalogResponse.model_validate(procedure_catalog)
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.delete("/delete-procedure-catalog/{procedure_id}",
    status_code=200,
    summary="Delete a procedure catalog",
    description="Delete an existing procedure catalog entry",
    responses={
        200: {
            "description": "Procedure catalog deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Procedure catalog deleted successfully"}
                }
            }
        },
        401: {"description": "Unauthorized"},
        404: {"description": "User or procedure catalog not found"},
        500: {"description": "Internal server error"}
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
    response_model=List[UserResponse],
    status_code=200,
    summary="Get all users", 
    description="Get all users in the system",
    responses={
        200: {
            "description": "List of all users",
            "model": List[UserResponse]
        },
        401: {"description": "Unauthorized"},
        404: {"description": "No users found"},
        500: {"description": "Internal server error"}
    }
)
async def get_all_users(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        users = db.query(User).all()
        if not users:
            return JSONResponse(status_code=404, content={"error": "No users found"})
        
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

        
        return JSONResponse(status_code=200, content=users_list)
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})

@user_router.get("/doctor-list",
    response_model=List[UserResponse],
    status_code=200,
    summary="Get all doctors",
    description="Get all doctors in the system",
    responses={
        200: {
            "description": "List of all doctors",
            "model": List[UserResponse]
        },
        401: {"description": "Unauthorized"},
        404: {"description": "No doctors found"},
        500: {"description": "Internal server error"}
    }
)
async def get_doctor_list(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        doctors = db.query(User).filter(User.user_type == "doctor").all()
        if not doctors:
            return JSONResponse(status_code=404, content={"error": "No doctors found"})
        
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

        return JSONResponse(status_code=200, content=doctors_list)
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {str(e)}"})