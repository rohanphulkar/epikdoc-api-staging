from fastapi import APIRouter, Depends, Request, File, UploadFile, BackgroundTasks, Body
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
import json, shutil

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
    
    The request can be sent in two ways:
    1. As multipart/form-data with:
       - json: A JSON string containing the profile fields:
         {
           "name": "John Doe",           # Optional: New display name
           "phone": "+1234567890",       # Optional: Phone with country code
           "bio": "Doctor profile..."    # Optional: Brief biography
         }
       - image: Optional profile image file
       
    2. As application/json with the same profile fields in request body
    
    Image requirements if provided:
    - Format: JPG/PNG
    - Max size: 5MB
    - Will be stored in uploads/profile_pictures directory
    - File path saved in user's profile_pic field
    
    All fields are optional - only provided fields will be updated.
    Returns a success message on successful update.
    """,
    responses={
        200: {
            "description": "Profile updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Profile updated successfully"
                    }
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Invalid phone number format"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Invalid or expired token"
                    }
                }
            }
        },
        404: {
            "description": "User not found",
            "content": {
                "application/json": {
                    "example": {
                        "error": "User not found"
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Failed to update profile"
                    }
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
            except:
                body = {}
        else:
            # Try to read raw JSON body
            try:
                raw_body = await request.body()
                if raw_body:
                    body = await request.json()
            except:
                pass

        # Get values from body dict with get() method
        name = body.get('name') if isinstance(body, dict) else None
        phone = body.get('phone') if isinstance(body, dict) else None 
        bio = body.get('bio') if isinstance(body, dict) else None

        if name:
            setattr(db_user, 'name', name)
        if phone:
            setattr(db_user, 'phone', phone)
        if bio:
            setattr(db_user, 'bio', bio)
            
        if image:
            # Read file contents
            file_contents = await image.read()

            # Check if the uploads directory exists, create it if it doesn't
            upload_dir = "uploads/profile_pictures"
            os.makedirs(upload_dir, exist_ok=True)
            
            # Save file to disk/storage
            file_name = f"profile_{db_user.id}_{image.filename}"
            file_path = f"{upload_dir}/{file_name}"
            
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
    
    # Pre-process gender mapping
    gender_map = df["Gender"].str.lower().map(lambda x: Gender.FEMALE if "f" in str(x) or "female" in str(x) else Gender.MALE)
    
    # Convert date columns once and handle NaT values
    dob_series = pd.to_datetime(df["Date of Birth"].astype(str), errors='coerce')
    anniversary_series = pd.to_datetime(df["Anniversary Date"].astype(str), errors='coerce')
    
    # Get all existing patient numbers for bulk lookup
    existing_patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(df["Patient Number"].astype(str).tolist())).all()
    }
    
    # Prepare bulk insert
    new_patients = []
    for idx, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            
            if patient_number in existing_patients:
                continue
            
            # Handle NaT values for dates by converting to None
            dob = None if pd.isna(dob_series[idx]) else dob_series[idx].to_pydatetime()
            anniversary = None if pd.isna(anniversary_series[idx]) else anniversary_series[idx].to_pydatetime()
                
            new_patients.append(Patient(
                doctor_id=user.id,
                patient_number=str(row.get("Patient Number", ""))[:255],
                name=str(row.get("Patient Name", ""))[:255],
                mobile_number=str(row.get("Mobile Number", ""))[:255],
                contact_number=str(row.get("Contact Number", ""))[:255],
                email=str(row.get("Email Address", ""))[:255],
                secondary_mobile=str(row.get("Secondary Mobile", ""))[:255],
                gender=gender_map[idx],
                address=str(row.get("Address", ""))[:255],
                locality=str(row.get("Locality", ""))[:255],
                city=str(row.get("City", ""))[:255],
                pincode=str(row.get("Pincode", ""))[:255],
                national_id=str(row.get("National Id", ""))[:255],
                date_of_birth=dob,
                age=str(row.get("Age", ""))[:5],
                anniversary_date=anniversary,
                blood_group=str(row.get("Blood Group", ""))[:50],
                remarks=str(row.get("Remarks", "")),
                medical_history=str(row.get("Medical History", "")),
                referred_by=str(row.get("Referred By", ""))[:255],
                groups=str(row.get("Groups", ""))[:255],
                patient_notes=str(row.get("Patient Notes", ""))
            ))
            
        except Exception as e:
            print(f"Error processing patient row {idx}: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing patient row {idx}: {str(e)}"})
    
    try:
        # Bulk insert all new patients
        if new_patients:
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
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }
    
    appointments = []
    for _, row in df.iterrows():
        try:
            status_str = str(row.get("Status", "SCHEDULED")).upper()
            status = AppointmentStatus.SCHEDULED if status_str == "SCHEDULED" else AppointmentStatus.CANCELLED

            patient_number = str(row.get("Patient Number", ""))
            patient = patients.get(patient_number)
            if patient:
                appointments.append(Appointment(
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
                ))
            
        except Exception as e:
            print(f"Error processing appointment row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing appointment row: {str(e)}"})

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

async def process_treatment_data(import_log: ImportLog, df: pd.DataFrame, db: Session):
    print("Processing treatment data")
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }

    treatments = []
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            patient = patients.get(patient_number)
            if patient:
                treatments.append(Treatment(
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
                ))
        except Exception as e:
            print(f"Error processing treatment row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing treatment row: {str(e)}"})

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

async def process_clinical_note_data(import_log: ImportLog, df: pd.DataFrame, db: Session):
    print("Processing clinical note data")
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }

    clinical_notes = []
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            patient = patients.get(patient_number)
            if patient:
                clinical_notes.append(ClinicalNote(
                    patient_id=patient.id,
                    date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                    doctor=str(row.get("Doctor", ""))[:255],
                    note_type=str(row.get("Type", ""))[:255],
                    description=str(row.get("Description", "")),
                    is_revised=bool(row.get("Revised", False))
                ))
        except Exception as e:
            print(f"Error processing clinical note row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing clinical note row: {str(e)}"})

    try:
        if clinical_notes:
            db.bulk_save_objects(clinical_notes)
            db.commit()
    except Exception as e:
        print(f"Error during bulk insert: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during bulk insert: {str(e)}"})

async def process_treatment_plan_data(import_log: ImportLog, df: pd.DataFrame, db: Session):
    print("Processing treatment plan data")
    
    # Pre-process all patient numbers and get patients in bulk
    patient_numbers = df["Patient Number"].astype(str).unique()
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }

    treatment_plans = []
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            patient = patients.get(patient_number)
            if patient:
                treatment_plans.append(TreatmentPlan(
                    patient_id=patient.id,
                    date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                    doctor=str(row.get("Doctor", ""))[:255],
                    treatment_name=str(row.get("Treatment Name", ""))[:255],
                    unit_cost=float(str(row.get("UnitCost", 0.0)).strip("'")),
                    quantity=int(float(str(row.get("Quantity", 1)).strip("'"))),
                    discount=float(str(row.get("Discount", 0)).strip("'")) if row.get("Discount") else None,
                    discount_type=str(row.get("DiscountType", ""))[:50],
                    amount=float(str(row.get("Amount", 0.0)).strip("'")),
                    treatment_description=str(row.get("Treatment Description", "")),
                    tooth_diagram=str(row.get("Tooth Diagram", ""))
                ))

        except Exception as e:
            print(f"Error processing treatment plan row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing treatment plan row: {str(e)}"})

    try:
        if treatment_plans:
            db.bulk_save_objects(treatment_plans)
            db.commit()
    except Exception as e:
        print(f"Error during bulk insert: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during bulk insert: {str(e)}"})

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

    # Safely convert numeric columns
    df["Amount Paid"] = df["Amount Paid"].apply(safe_float_convert)
    df["Refunded amount"] = df["Refunded amount"].apply(lambda x: safe_float_convert(x) if pd.notna(x) else None)
    df["Vendor Fees Percent"] = df["Vendor Fees Percent"].apply(lambda x: safe_float_convert(x) if pd.notna(x) else None)
    df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
    df["Patient Number"] = df["Patient Number"].astype(str)
    
    # Get all unique patient numbers
    patient_numbers = df["Patient Number"].unique()
    
    # Bulk fetch all patients in one query
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }
    
    payments = []
    for _, row in df.iterrows():
        patient_number = row["Patient Number"]
        patient = patients.get(patient_number)
        
        if  patient:            
            payment = Payment(
                date=row["Date"] if pd.notna(row["Date"]) else None,
                doctor_id=user.id,
                patient_id=patient.id,
                patient_number=str(row.get("Patient Number", ""))[:255],
                patient_name=str(row.get("Patient Name", ""))[:255],
                receipt_number=str(row.get("Receipt Number", ""))[:255],
                treatment_name=str(row.get("Treatment name", ""))[:255],
                amount_paid=row["Amount Paid"],
                invoice_number=str(row.get("Invoice Number", ""))[:255],
                notes=str(row.get("Notes", "")),
                refund=bool(row.get("Refund", False)),
                refund_receipt_number=str(row.get("Refund Receipt Number", ""))[:255],
                refunded_amount=row["Refunded amount"],
                payment_mode=str(row.get("Payment Mode", ""))[:255],
                card_number=str(row.get("Card Number", ""))[:255],
                card_type=str(row.get("Card Type", ""))[:255],
                cheque_number=str(row.get("Cheque Number", ""))[:255],
                cheque_bank=str(row.get("Cheque Bank", ""))[:255],
                netbanking_bank_name=str(row.get("Netbanking Bank Name", ""))[:255],
                vendor_name=str(row.get("Vendor Name", ""))[:255],
                vendor_fees_percent=row["Vendor Fees Percent"],
                cancelled=bool(row.get("Cancelled", False))
            )
            payments.append(payment)

    try:
        if payments:
            db.bulk_save_objects(payments)
            db.commit()
    except Exception as e:
        print(f"Error during bulk insert: {str(e)}")
        db.rollback()
        import_log.status = ImportStatus.FAILED
        db.commit()
        return JSONResponse(status_code=400, content={"error": f"Error during bulk insert: {str(e)}"})

async def process_invoice_data(import_log: ImportLog, df: pd.DataFrame, db: Session, user: User):
    print("Processing invoice data")
    
    # Get all unique patient numbers from the dataframe
    patient_numbers = df["Patient Number"].unique()
    
    # Bulk fetch all patients in one query
    patients = {
        p.patient_number: p for p in 
        db.query(Patient).filter(Patient.patient_number.in_(patient_numbers)).all()
    }
    
    invoices = []
    for _, row in df.iterrows():
        try:
            patient_number = str(row.get("Patient Number", ""))
            patient = patients.get(patient_number)
            
            if patient:
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

                invoice = Invoice(
                    date=pd.to_datetime(str(row.get("Date"))) if row.get("Date") else None,
                    doctor_id=user.id,
                    patient_id=patient.id,
                    patient_number=str(row.get("Patient Number", ""))[:255],
                    patient_name=str(row.get("Patient Name", ""))[:255],
                    doctor_name=str(row.get("Doctor Name", ""))[:255],
                    invoice_number=str(row.get("Invoice Number", ""))[:255],
                    treatment_name=str(row.get("Treatment Name", ""))[:255],
                    unit_cost=safe_parse_number(row.get("Unit Cost"), float, 0.0),
                    quantity=safe_parse_number(row.get("Quantity"), int, 1),
                    discount=safe_parse_number(row.get("Discount"), float),
                    discount_type=discount_type,
                    type=str(row.get("Type", ""))[:255],
                    invoice_level_tax_discount=safe_parse_number(row.get("Invoice Level Tax Discount"), float),
                    tax_name=str(row.get("Tax name", ""))[:255],
                    tax_percent=safe_parse_number(row.get("Tax Percent"), float),
                    cancelled=bool(row.get("Cancelled", False)),
                    notes=str(row.get("Notes", "")),
                    description=str(row.get("Description", ""))
                )
                invoices.append(invoice)
            
        except Exception as e:
            print(f"Error processing invoice row: {str(e)}")
            db.rollback()
            import_log.status = ImportStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": f"Error processing invoice row: {str(e)}"})

    # Bulk save all invoices at once
    try:
        if invoices:
            db.bulk_save_objects(invoices)
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
        procedures = [
            ProcedureCatalog(
                user_id=user.id,
                treatment_name=row['treatment_name'],
                treatment_cost=row['treatment_cost'], 
                treatment_notes=row['treatment_notes'],
                locale=row['locale']
            )
            for _, row in df.iterrows()
        ]

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
                with zipfile.ZipFile(file_path, "r") as zip_ref:
                    zip_ref.extractall(f"uploads/imports/{uuid}")
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
        csv_files = [f for f in os.listdir(f"uploads/imports/{uuid}") if f.endswith('.csv')]
        print(f"Found CSV files: {csv_files}")
        if not csv_files:
            print("No CSV files found")
            import_log.status = ImportStatus.FAILED
            db.commit()
            return

        # Define processing order and file name patterns
        file_types = [
            {
                "patterns": ["patients", "patient"],
                "processor": process_patient_data
            },
            {
                "patterns": ["appointments", "appointment"],
                "processor": process_appointment_data
            },
            {
                "patterns": ["treatment.csv"],
                "processor": process_treatment_data
            },
            {
                "patterns": ["clinicalnotes", "clinical-notes", "clinical_notes"],
                "processor": process_clinical_note_data
            },
            {
                "patterns": ["treatmentplans", "treatment-plans", "treatment_plans"],
                "processor": process_treatment_plan_data
            },
            {
                "patterns": ["expenses", "expense"],
                "processor": process_expense_data
            },
            {
                "patterns": ["payments", "payment"],
                "processor": process_payment_data
            },
            {
                "patterns": ["invoices", "invoice"],
                "processor": process_invoice_data
            },
            {
                "patterns": ["procedurecatalog", "procedure-catalog", "procedure_catalog"],
                "processor": process_procedure_catalog_data
            }
        ]

        # Process files in order
        for file_type in file_types:
            print(f"\nProcessing file type: {file_type['patterns']}")
            for filename in csv_files:
                normalized_filename = filename.lower()
                
                # Check if current file matches any pattern for this type
                if any(pattern in normalized_filename for pattern in file_type["patterns"]):
                    print(f"\nProcessing file: {filename}")
                    try:
                        print(f"Reading CSV file: {filename}")
                        df = pd.read_csv(f"uploads/imports/{uuid}/{filename}", keep_default_na=False)
                        df = df.fillna("")
                        print(f"Successfully read CSV with {len(df)} rows")
                        
                        # Call appropriate processor function
                        processor = file_type["processor"]
                        if processor in [process_patient_data, process_appointment_data, process_expense_data, 
                                      process_payment_data, process_invoice_data, process_procedure_catalog_data]:
                            await processor(import_log, df, db, user)
                        else:
                            await processor(import_log, df, db)
                            
                    except Exception as e:
                        print(f"Error processing file {filename}: {str(e)}")
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
        shutil.rmtree(f"uploads/imports/{uuid}")
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
        uuid = generate_uuid()
        # Create uploads directory if it doesn't exist
        upload_dir = os.path.join("uploads", "imports", uuid)
        os.makedirs(upload_dir, exist_ok=True)
        
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
        
        import_logs = db.query(ImportLog).filter(ImportLog.user_id == user.id).order_by(ImportLog.created_at.desc()).all()
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